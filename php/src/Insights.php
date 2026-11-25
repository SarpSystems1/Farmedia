<?php
/**
 * Rule-based recommendations and warnings from the forecast and the farm profile.
 * Port of services/insights.py. Same rules, same order, same thresholds.
 */

declare(strict_types=1);

namespace Farmedia;

final class Insights
{
    private const SEVERITY_ORDER = ['danger' => 0, 'warning' => 1, 'info' => 2, 'good' => 3];

    /**
     * @param array<string, mixed> $forecast the output of Weather::forecast()
     * @param list<array<string, mixed>> $cropsLast
     * @param list<array<string, mixed>> $cropsCurrent
     * @param list<array<string, mixed>> $cropsNext
     * @return list<array<string, mixed>>
     */
    public static function build(
        array $forecast,
        string $lang,
        string $role,
        ?float $farmSize,
        array $cropsLast,
        array $cropsCurrent,
        array $cropsNext
    ): array {
        $cur = is_array($forecast['current'] ?? null) ? $forecast['current'] : [];
        $daily = is_array($forecast['daily'] ?? null) ? $forecast['daily'] : [];
        $hourly = is_array($forecast['hourly'] ?? null) ? $forecast['hourly'] : [];

        $day = static function (string $key, int $n) use ($daily): array {
            $values = array_slice(is_array($daily[$key] ?? null) ? $daily[$key] : [], 0, $n);
            return array_values(array_map(
                static fn ($x): float => self::num($x),
                array_filter($values, static fn ($x): bool => $x !== null)
            ));
        };

        $mins3 = $day('temperature_2m_min', 3);
        $maxs3 = $day('temperature_2m_max', 3);
        $min3 = $mins3 !== [] ? min($mins3) : self::num($cur['temperature_2m'] ?? null, 15.0);
        $max3 = $maxs3 !== [] ? max($maxs3) : self::num($cur['temperature_2m'] ?? null, 20.0);
        $rain3 = array_sum($day('precipitation_sum', 3));
        $rainToday = ($day('precipitation_sum', 1)[0] ?? 0.0);
        $probToday = ($day('precipitation_probability_max', 1)[0] ?? 0.0);
        $windMax = max([...$day('wind_speed_10m_max', 2), self::num($cur['wind_speed_10m'] ?? null)]);
        $gusts = self::num($cur['wind_gusts_10m'] ?? null);
        $temp = self::num($cur['temperature_2m'] ?? null, ($min3 + $max3) / 2);
        $hum = self::num($cur['relative_humidity_2m'] ?? null, 50.0);
        $precipNow = self::num($cur['precipitation'] ?? null);
        $windNow = self::num($cur['wind_speed_10m'] ?? null);

        $cut = static fn (string $key): array => array_slice(is_array($hourly[$key] ?? null) ? $hourly[$key] : [], 0, 72);
        $frost = Frost::analyze([
            'time' => $cut('time'),
            'temperature_2m' => $cut('temperature_2m'),
            'dew_point_2m' => $cut('dew_point_2m'),
            'wind_speed_10m' => $cut('wind_speed_10m'),
        ]);
        $frostName = Translate::t($lang, (string) $frost['frost_type']);
        $hobby = $role === 'hobby';

        $out = [];
        $add = static function (
            string $kind, string $name, string $icon, string $severity, ?string $textKey = null, array $params = []
        ) use (&$out, $lang): void {
            $out[] = [
                'id' => $name,
                'type' => $kind,          // "recommend" | "avoid"
                'icon' => $icon,
                'severity' => $severity,
                'title' => Translate::t($lang, "ins.$name.title"),
                'text' => Translate::t($lang, $textKey ?? "ins.$name.text", $params),
            ];
        };

        // ---- Weather-driven (everyone) ----
        if ($min3 <= 0) {
            $add('avoid', 'frost_avoid', '❄️', 'danger', null, ['temp' => self::fmt($min3), 'frost' => $frostName]);
            $hobby ? $add('recommend', 'frost_rec_hobby', '🧺', 'warning')
                   : $add('recommend', 'frost_rec', '🧯', 'warning');
        } elseif ($min3 <= 3) {
            $add('avoid', 'frost_watch', '🌡️', 'warning', null, ['temp' => self::fmt($min3)]);
        }

        if ($max3 >= 35) {
            $add('avoid', 'heat_avoid', '🔥', 'danger', null, ['temp' => self::fmt($max3)]);
            $add('recommend', 'heat_rec', '💧', 'warning');
        }

        $rainy = $probToday >= 60 || $rainToday >= 5 || $precipNow > 0;
        if ($rainy) {
            $add('avoid', 'rain_avoid', '🌧️', 'warning', null, ['prob' => (string) (int) $probToday, 'mm' => self::fmt($rainToday)]);
            $add('recommend', 'rain_rec', '🚰', 'info');
        }

        $gust = max($windMax, $gusts);
        if ($gust >= 30) {
            $add('avoid', 'wind_avoid', '💨', 'warning', null, ['wind' => self::fmt($gust)]);
            $add('recommend', 'wind_rec', '🏗️', 'info');
        }

        if ($hum >= 85 && $temp >= 8 && $temp <= 26) {
            $add('avoid', 'fungal_avoid', '🍄', 'warning', null, ['hum' => (string) (int) $hum, 'temp' => self::fmt($temp)]);
            $add('recommend', 'fungal_rec', '🔍', 'info');
        }

        $dry = $rain3 < 1 && $max3 >= 22 && !$rainy;
        if ($dry) {
            if (!$hobby && $farmSize) {
                $add('recommend', 'dry_rec', '🚿', 'warning', 'ins.dry_rec_farm.text',
                    ['mm' => self::fmt($rain3), 'temp' => self::fmt($max3), 'size' => self::fmt($farmSize)]);
            } else {
                $add('recommend', 'dry_rec', '🚿', 'warning', null, ['mm' => self::fmt($rain3), 'temp' => self::fmt($max3)]);
            }
        }

        if (!$rainy && $windNow < 12 && $windMax < 20 && $temp >= 10 && $temp <= 28 && $probToday < 30) {
            $add('recommend', 'spray_rec', '🧪', 'good', null, ['wind' => self::fmt($windNow), 'temp' => self::fmt($temp)]);
        }

        // ---- Crop-driven ----
        $watched = $cropsCurrent !== [] ? $cropsCurrent : ($hobby ? $cropsNext : []);
        if ($watched !== []) {
            $frostHit = array_values(array_filter($watched, static fn (array $c): bool => $min3 <= $c['frost_c'] + 1));
            if ($frostHit !== []) {
                $add('avoid', 'crop_frost', '🌱', 'danger', null, ['crops' => self::names($frostHit), 'temp' => self::fmt($min3)]);
            }
            $heatHit = array_values(array_filter($watched, static fn (array $c): bool => $max3 >= $c['heat_c']));
            if ($heatHit !== []) {
                $add('avoid', 'crop_heat', '🥵', 'warning', null, ['crops' => self::names($heatHit), 'temp' => self::fmt($max3)]);
            }
            if ($rain3 < 3 && !$rainy) {
                $thirsty = array_values(array_filter($watched, static fn (array $c): bool => $c['water'] === 'high'));
                if ($thirsty !== []) {
                    $add('recommend', 'crop_water', '🪣', 'warning', null, ['crops' => self::names($thirsty)]);
                }
            }
        }

        if (!$hobby) {
            $lastFamilies = array_column($cropsLast, 'family');
            $familiesPrev = array_unique([...$lastFamilies, ...array_column($cropsCurrent, 'family')]);
            $repeat = array_values(array_filter($cropsCurrent, static fn (array $c): bool => in_array($c['family'], $lastFamilies, true)));
            $repeatIds = array_column($repeat, 'id');
            foreach ($cropsNext as $c) {
                if (in_array($c['family'], $familiesPrev, true) && !in_array($c['id'], $repeatIds, true)) {
                    $repeat[] = $c;
                    $repeatIds[] = $c['id'];
                }
            }
            if ($repeat !== []) {
                $add('avoid', 'rotation_avoid', '🔁', 'warning', null, ['crops' => self::names($repeat)]);
            } elseif (($cropsLast !== [] || $cropsCurrent !== [] || $cropsNext !== [])
                && !in_array('legume', array_column([...$cropsCurrent, ...$cropsNext], 'family'), true)) {
                $add('recommend', 'rotation_rec', '🫘', 'info');
            }
        }

        $hasRecommend = false;
        foreach ($out as $item) {
            if ($item['type'] === 'recommend') {
                $hasRecommend = true;
                break;
            }
        }
        if (!$hasRecommend && $temp >= 10 && $temp <= 30 && !$rainy && $windMax < 25) {
            $add('recommend', 'good_rec', '🌤️', 'good', null, ['temp' => self::fmt($temp)]);
        }

        // Stable sort by severity, as Python's sort is stable.
        usort($out, static fn (array $a, array $b): int =>
            (self::SEVERITY_ORDER[$a['severity']] ?? 9) <=> (self::SEVERITY_ORDER[$b['severity']] ?? 9));
        return $out;
    }

    private static function num(mixed $v, float $default = 0.0): float
    {
        return (is_int($v) || is_float($v)) ? (float) $v : $default;
    }

    /** One decimal, without trailing zeros: 12.0 -> "12", 3.5 -> "3.5". Same as the Python _fmt. */
    private static function fmt(float $v): string
    {
        return rtrim(rtrim(sprintf('%.1f', $v), '0'), '.');
    }

    /** @param list<array<string, mixed>> $crops */
    private static function names(array $crops): string
    {
        return implode(', ', array_column($crops, 'name'));
    }
}
