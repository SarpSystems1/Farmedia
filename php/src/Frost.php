<?php
/**
 * Pre-dawn frost analysis (00:00-08:00). Port of services/frost_engine.py, same thresholds.
 */

declare(strict_types=1);

namespace Farmedia;

final class Frost
{
    /**
     * @param array{time?: list<string>, temperature_2m?: list<?float>, wind_speed_10m?: list<?float>} $hourly
     * @return array<string, mixed>
     */
    public static function analyze(array $hourly): array
    {
        $times = $hourly['time'] ?? [];
        $temps = $hourly['temperature_2m'] ?? [];
        $winds = $hourly['wind_speed_10m'] ?? [];

        if ($temps === [] || $times === []) {
            return [
                'risk_score' => 0,
                'risk_level' => 'risk.level.none',
                'frost_type' => 'frost.type.none',
                'min_temp' => 0.0,
                'details' => 'Yetersiz hava durumu verisi.',
            ];
        }

        // Keep the hours between 00:00 and 08:00. zip() semantics: stop at the shorter list.
        $dawnTemps = [];
        $dawnWinds = [];
        $n = min(count($times), count($temps));
        for ($i = 0; $i < $n; $i++) {
            $parts = explode('T', (string) $times[$i]);
            if (!isset($parts[1])) {
                continue;
            }
            $hour = (int) explode(':', $parts[1])[0];
            if ($hour >= 0 && $hour <= 8) {
                $dawnTemps[] = (float) $temps[$i];
                $wind = $winds[$i] ?? null;
                $dawnWinds[] = $wind === null ? 0.0 : (float) $wind;
            }
        }

        if ($dawnTemps === []) {
            $dawnTemps = array_map('floatval', array_slice($temps, 0, 8));
            $dawnWinds = $winds === [] ? array_fill(0, count($dawnTemps), 0.0)
                : array_map(static fn ($w) => $w === null ? 0.0 : (float) $w, array_slice($winds, 0, 8));
        }

        $minTemp = min($dawnTemps);
        $avgWind = $dawnWinds === [] ? 0.0 : array_sum($dawnWinds) / count($dawnWinds);

        if ($minTemp > 2.0) {
            $score = 0;
            $level = 'risk.level.none';
            $type = 'frost.type.none';
        } elseif ($minTemp > 0.0 && $minTemp <= 2.0) {
            $score = 30;
            $level = 'risk.level.low';
            $type = 'frost.type.white';
        } else {
            // 0 °C and below: the colder, the higher the risk. -5 °C and under is critical.
            $tempFactor = min(100.0, abs($minTemp) * 15.0);
            if ($avgWind >= 15.0) {
                $type = 'frost.type.advective';
                $score = (int) min(100, $tempFactor * 1.1);
            } elseif ($avgWind < 4.0 && $minTemp <= -2.0) {
                $type = 'frost.type.black';
                $score = (int) min(100, $tempFactor * 1.2);
            } else {
                $type = 'frost.type.white';
                $score = (int) min(100, $tempFactor);
            }
            if ($score >= 80) {
                $level = 'risk.level.critical';
            } elseif ($score >= 60) {
                $level = 'risk.level.high';
            } elseif ($score >= 30) {
                $level = 'risk.level.moderate';
            } else {
                $level = 'risk.level.low';
            }
        }

        return [
            'risk_score' => $score,
            'risk_level' => $level,
            'frost_type' => $type,
            'min_temp' => round($minTemp, 1),
            'avg_wind_speed' => round($avgWind, 1),
        ];
    }
}
