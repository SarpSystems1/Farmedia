<?php
/**
 * Location lookup for the profile form, with OpenStreetMap Nominatim.
 * Port of services/geocoding.py: the most specific place first, then relaxed up to the country.
 *
 * Nominatim asks for at most one request per second. The Python version enforces that with a lock.
 * PHP requests do not share memory, so this version does not throttle. Keep traffic low, or add a
 * shared cache table before running it at scale.
 */

declare(strict_types=1);

namespace Farmedia;

final class Geocoding
{
    private const URL = 'https://nominatim.openstreetmap.org/search';
    private const USER_AGENT = 'User-Agent: Farmedia/2.0 (agricultural weather assistant)';

    /**
     * @return array{latitude: float, longitude: float, display_name: string, country_code: ?string, precision: string}
     */
    public static function locate(string $country, string $state, string $city, string $district, string $lang): array
    {
        $country = trim($country);
        $state = trim($state);
        $city = trim($city);
        $district = trim($district);
        if ($country === '' && $city === '') {
            throw ApiException::invalidInput('location', 'Country or city is required.');
        }

        // A known country limits every lookup to that country. An unknown one is not limited.
        $code = Regions::resolve(null, $country);

        // Most specific first. Drop the finest level until something matches.
        $levels = [$district, $city, $state, $country];
        $names = ['district', 'city', 'state', 'country'];
        $tried = [];
        for ($start = 0; $start < count($levels); $start++) {
            $parts = array_values(array_filter(array_slice($levels, $start), static fn (string $p): bool => $p !== ''));
            if ($parts === []) {
                continue;
            }
            $q = implode(', ', $parts);
            if (isset($tried[$q])) {
                continue;
            }
            $tried[$q] = true;

            $hit = self::query($q, $lang, $code);
            if ($hit !== null) {
                // The precision is the finest level that was really searched.
                for ($i = $start; $i < count($levels); $i++) {
                    if ($levels[$i] !== '') {
                        $hit['precision'] = $names[$i];
                        break;
                    }
                }
                return $hit;
            }
        }

        throw ApiException::locationNotFound(implode(', ', array_filter($levels, static fn (string $p): bool => $p !== '')));
    }

    /** @return array{latitude: float, longitude: float, display_name: string, country_code: ?string, precision: string}|null */
    private static function query(string $q, string $lang, ?string $code): ?array
    {
        $params = [
            'q' => $q,
            'format' => 'jsonv2',
            'limit' => 1,
            'addressdetails' => 1,
            'accept-language' => $lang,
        ];
        if ($code !== null) {
            $params['countrycodes'] = strtolower($code);
        }

        $data = Http::getJson(self::URL, $params, 10, [self::USER_AGENT]);
        if ($data === []) {
            return null;
        }
        $hit = $data[0];
        $address = is_array($hit['address'] ?? null) ? $hit['address'] : [];
        $country = strtoupper((string) ($address['country_code'] ?? ''));

        return [
            'latitude' => round((float) $hit['lat'], 5),
            'longitude' => round((float) $hit['lon'], 5),
            'display_name' => (string) ($hit['display_name'] ?? $q),
            'country_code' => $country !== '' ? $country : null,
            'precision' => 'country',   // replaced by locate() with the finest level that matched
        ];
    }
}
