<?php
/**
 * Location and short-range weather for the Sarp AI prompt, from Open-Meteo (no API key needed).
 *
 * This is a deliberately small version: a three-day range, rain and a simple frost flag. The full
 * frost model is services/frost_engine.py, which stays in the Python app for the dashboard.
 */

declare(strict_types=1);

namespace Farmedia;

final class Weather
{
    private const GEOCODE_URL = 'https://geocoding-api.open-meteo.com/v1/search';
    private const FORECAST_URL = 'https://api.open-meteo.com/v1/forecast';

    /** A night minimum at or below this (°C) is flagged as frost risk. */
    public const FROST_C = 2.0;

    /**
     * The best match for a city name, limited to a country when its code is known.
     *
     * @return array{latitude: float, longitude: float, name: string}
     */
    public static function geocode(string $city, ?string $countryCode): array
    {
        $query = ['name' => $city, 'count' => 1, 'language' => 'en', 'format' => 'json'];
        if ($countryCode !== null) {
            $query['countryCode'] = $countryCode;
        }

        $data = Http::getJson(self::GEOCODE_URL, $query, 10);
        $hit = $data['results'][0] ?? null;
        if (!is_array($hit) || !isset($hit['latitude'], $hit['longitude'])) {
            throw ApiException::locationNotFound($city);
        }
        return [
            'latitude' => (float) $hit['latitude'],
            'longitude' => (float) $hit['longitude'],
            'name' => (string) ($hit['name'] ?? $city),
        ];
    }

    /**
     * Current conditions, 48-hour hourly series and a 7-day daily forecast, as the dashboard uses them.
     * Port of services/weather_service.get_forecast. Coordinates are rounded to 4 decimals (about 11 m).
     *
     * @return array<string, mixed>
     */
    public static function forecast(float $latitude, float $longitude): array
    {
        if ($latitude < -90 || $latitude > 90 || $longitude < -180 || $longitude > 180) {
            throw ApiException::invalidInput('coordinates', 'Coordinates out of range.');
        }
        // pressure_msl is sea-level pressure. surface_pressure reads about 810 hPa at 1,900 m, which looked wrong.
        return Http::getJson(self::FORECAST_URL, [
            'latitude' => round($latitude, 4),
            'longitude' => round($longitude, 4),
            'current' => 'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,'
                . 'weather_code,wind_speed_10m,wind_gusts_10m,pressure_msl,is_day',
            'hourly' => 'temperature_2m,dew_point_2m,wind_speed_10m,soil_temperature_0cm',
            'daily' => 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,'
                . 'precipitation_probability_max,wind_speed_10m_max,uv_index_max',
            'forecast_days' => 7,
            'models' => 'ecmwf_ifs025',
            'timezone' => 'auto',
        ], 12);
    }

    /** Three days of temperature range and rain, with a frost flag, as plain text for the prompt. */
    public static function summary(float $latitude, float $longitude): string
    {
        $data = Http::getJson(self::FORECAST_URL, [
            'latitude' => $latitude,
            'longitude' => $longitude,
            'daily' => 'temperature_2m_min,temperature_2m_max,precipitation_sum',
            'timezone' => 'auto',
            'forecast_days' => 3,
        ], 10);

        $daily = is_array($data['daily'] ?? null) ? $data['daily'] : [];
        $dates = is_array($daily['time'] ?? null) ? $daily['time'] : [];
        $mins = is_array($daily['temperature_2m_min'] ?? null) ? $daily['temperature_2m_min'] : [];
        $maxs = is_array($daily['temperature_2m_max'] ?? null) ? $daily['temperature_2m_max'] : [];
        $rain = is_array($daily['precipitation_sum'] ?? null) ? $daily['precipitation_sum'] : [];

        $lines = [];
        $frost = false;
        foreach ($dates as $i => $date) {
            $min = isset($mins[$i]) ? (float) $mins[$i] : null;
            $max = isset($maxs[$i]) ? (float) $maxs[$i] : null;
            $mm = isset($rain[$i]) ? (float) $rain[$i] : null;
            if ($min !== null && $min <= self::FROST_C) {
                $frost = true;
            }
            $lines[] = sprintf(
                '%s: min %s C, max %s C, rain %s mm',
                (string) $date,
                $min === null ? 'n/a' : (string) round($min, 1),
                $max === null ? 'n/a' : (string) round($max, 1),
                $mm === null ? 'n/a' : (string) round($mm, 1)
            );
        }
        if ($lines === []) {
            throw ApiException::upstreamFailure('The forecast had no daily data.');
        }

        return implode("\n", $lines) . "\nFrost risk in the next 3 days: " . ($frost ? 'yes' : 'no');
    }
}
