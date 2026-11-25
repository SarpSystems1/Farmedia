<?php
/**
 * Agricultural supplier lookup (seed, machinery and input shops) from OpenStreetMap via Overpass.
 * Port of services/suppliers.py. The mirrors are tried in turn, with one retry each and a total
 * time budget. There is no cache here: a shared cache table is the place to add one.
 */

declare(strict_types=1);

namespace Farmedia;

final class Suppliers
{
    /** Public Overpass mirrors, tried in order (same order as the Python version). */
    private const MIRRORS = [
        'https://overpass-api.de/api/interpreter',
        'https://overpass.openstreetmap.fr/api/interpreter',
        'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
        'https://overpass.kumi.systems/api/interpreter',
    ];
    private const USER_AGENT = 'User-Agent: Farmedia/2.0 (agricultural weather assistant)';
    private const OVERPASS_TIMEOUT_S = 40;
    private const HTTP_TIMEOUT_S = 45.0;
    private const FETCH_BUDGET_S = 75.0;
    private const RETRIES_PER_MIRROR = 1;
    private const RETRYABLE_STATUS = [429, 502, 503, 504];
    private const MAX_RESULTS = 15;
    private const MAX_FETCH = 100;

    private const CATEGORY_PATTERNS = [
        'seed' => '/tohum|seed|fide|fidan|nursery|sapling/u',
        'machinery' => '/traktor|tractor|makin|machin|ekipman|equipment|motor|sulama|irrigat/u',
    ];

    /** Search shortcuts opened in the browser (Google Maps), in the UI language. */
    private const SEARCH_TERMS = [
        'tr' => ['seed' => 'tohumcu', 'machinery' => 'tarım makineleri bayii', 'inputs' => 'tarım ilacı gübre bayii'],
        'en' => ['seed' => 'seed store', 'machinery' => 'farm machinery dealer', 'inputs' => 'agricultural supplies fertiliser pesticide'],
    ];

    /** The search radius follows how precisely the location is known. */
    private const RADIUS_KM = ['district' => 15, 'city' => 40, 'state' => 80, 'country' => 200];
    private const DEFAULT_RADIUS_KM = 40;

    public static function radiusForPrecision(?string $precision): int
    {
        return self::RADIUS_KM[$precision ?? ''] ?? self::DEFAULT_RADIUS_KM;
    }

    /**
     * Up to 15 mapped suppliers, nearest first.
     *
     * @return list<array<string, mixed>>
     */
    public static function find(float $latitude, float $longitude, float $radiusKm): array
    {
        $data = self::fetch(self::query($latitude, $longitude, (int) ($radiusKm * 1000)));

        $items = [];
        foreach (is_array($data['elements'] ?? null) ? $data['elements'] : [] as $el) {
            $tags = is_array($el['tags'] ?? null) ? $el['tags'] : [];
            $center = is_array($el['center'] ?? null) ? $el['center'] : [];
            $lat = $el['lat'] ?? ($center['lat'] ?? null);
            $lon = $el['lon'] ?? ($center['lon'] ?? null);
            if ($lat === null || $lon === null) {
                continue;
            }
            $items[] = [
                'name' => self::text($tags['name'] ?? null),
                'category' => self::category($tags),
                'distance_km' => round(self::distanceKm($latitude, $longitude, (float) $lat, (float) $lon), 1),
                'address' => self::address($tags),
                'phone' => self::text($tags['phone'] ?? null) ?? self::text($tags['contact:phone'] ?? null),
                'website' => self::text($tags['website'] ?? null) ?? self::text($tags['contact:website'] ?? null),
                'opening_hours' => self::text($tags['opening_hours'] ?? null),
                'osm_url' => 'https://www.openstreetmap.org/' . ($el['type'] ?? 'node') . '/' . ($el['id'] ?? ''),
            ];
        }

        usort($items, static fn (array $a, array $b): int => $a['distance_km'] <=> $b['distance_km']);
        return array_slice($items, 0, self::MAX_RESULTS);
    }

    /**
     * Map search links for the place the user chose, e.g. "seed store, Bursa, Turkey".
     * Only the known parts are used, so no country is guessed.
     *
     * @param list<?string> $placeParts most specific first (city, state, country name)
     * @return list<array{category: string, url: string}>
     */
    public static function searchLinks(string $lang, array $placeParts): array
    {
        $terms = self::SEARCH_TERMS[$lang === 'tr' ? 'tr' : 'en'];

        $seen = [];
        $parts = [];
        foreach ($placeParts as $p) {
            $p = trim((string) $p);
            $key = mb_strtolower($p, 'UTF-8');
            if ($p !== '' && !isset($seen[$key])) {
                $seen[$key] = true;   // "Berlin" as city and as state is one place, not two
                $parts[] = $p;
            }
        }
        $place = mb_substr(implode(', ', $parts), 0, 200, 'UTF-8');

        $links = [];
        foreach ($terms as $category => $term) {
            $q = trim($term . ' ' . $place);
            $links[] = [
                'category' => $category,
                'url' => 'https://www.google.com/maps/search/?api=1&query=' . urlencode($q),
            ];
        }
        return $links;
    }

    private static function query(float $lat, float $lon, int $radiusM): string
    {
        $around = '(around:' . $radiusM . ',' . $lat . ',' . $lon . ')';
        return '[out:json][timeout:' . self::OVERPASS_TIMEOUT_S . '];('
            . 'nwr["shop"="agrarian"]' . $around . ';'
            . 'nwr["shop"="garden_centre"]' . $around . ';'
            . ');out center tags ' . self::MAX_FETCH . ';';
    }

    /**
     * Posts the query to each mirror in turn until one answers, within FETCH_BUDGET_S.
     *
     * @return array<mixed>
     */
    private static function fetch(string $query): array
    {
        set_time_limit((int) self::FETCH_BUDGET_S + 30);
        $errors = [];
        $deadline = microtime(true) + self::FETCH_BUDGET_S;
        $body = http_build_query(['data' => $query]);

        foreach (self::MIRRORS as $url) {
            $host = (string) parse_url($url, PHP_URL_HOST);
            for ($attempt = 0; $attempt <= self::RETRIES_PER_MIRROR; $attempt++) {
                $remaining = $deadline - microtime(true);
                if ($remaining <= 0) {
                    $errors[] = 'time budget exhausted';
                    throw ApiException::upstreamFailure('Overpass unavailable: ' . implode('; ', $errors));
                }
                if ($attempt > 0) {
                    usleep((int) (min(2.0 * $attempt, $remaining) * 1_000_000));
                }

                $timeout = (int) max(1.0, min(self::HTTP_TIMEOUT_S, $deadline - microtime(true)));
                $result = Http::send('POST', $url, [
                    self::USER_AGENT,
                    'Content-Type: application/x-www-form-urlencoded',
                    'Accept: application/json',
                ], $body, $timeout);

                if ($result['error'] !== 0) {
                    $errors[] = $host . ': ' . ($result['error'] === CURLE_OPERATION_TIMEDOUT ? 'TimeoutException' : 'RequestError');
                    continue;
                }
                if ($result['status'] === 200) {
                    $data = json_decode($result['body'], true);
                    if (is_array($data)) {
                        return $data;
                    }
                    $errors[] = $host . ': invalid json';
                    break;
                }
                $errors[] = $host . ': status ' . $result['status'];
                if (!in_array($result['status'], self::RETRYABLE_STATUS, true)) {
                    break;
                }
            }
        }
        throw ApiException::upstreamFailure('Overpass unavailable: ' . implode('; ', $errors));
    }

    /** @param array<string, mixed> $tags */
    private static function category(array $tags): string
    {
        if (($tags['shop'] ?? null) === 'garden_centre') {
            return 'garden';
        }
        $haystack = self::fold(implode(' ', [
            (string) ($tags['name'] ?? ''), (string) ($tags['operator'] ?? ''),
            (string) ($tags['brand'] ?? ''), (string) ($tags['description'] ?? ''),
        ]));
        foreach (self::CATEGORY_PATTERNS as $category => $pattern) {
            if (preg_match($pattern, $haystack) === 1) {
                return $category;
            }
        }
        return 'inputs';
    }

    /** Lower case with Turkish letters folded, so keyword matching works in both spellings. */
    private static function fold(string $s): string
    {
        $s = strtr($s, ['İ' => 'i', 'I' => 'i']);
        $s = mb_strtolower($s, 'UTF-8');
        return strtr($s, ['ı' => 'i', 'ş' => 's', 'ğ' => 'g', 'ü' => 'u', 'ö' => 'o', 'ç' => 'c']);
    }

    /** @param array<string, mixed> $tags */
    private static function address(array $tags): string
    {
        $full = self::text($tags['addr:full'] ?? null);
        if ($full !== null) {
            return $full;
        }
        $street = implode(' ', array_filter([self::text($tags['addr:street'] ?? null), self::text($tags['addr:housenumber'] ?? null)]));
        return implode(', ', array_filter([$street, self::text($tags['addr:district'] ?? null), self::text($tags['addr:city'] ?? null)]));
    }

    /** A non-empty string from an OSM tag, or null. */
    private static function text(mixed $value): ?string
    {
        if (!is_string($value) && !is_int($value) && !is_float($value)) {
            return null;
        }
        $s = trim((string) $value);
        return $s === '' ? null : $s;
    }

    private static function distanceKm(float $lat1, float $lon1, float $lat2, float $lon2): float
    {
        $r = 6371.0;
        $p1 = deg2rad($lat1);
        $p2 = deg2rad($lat2);
        $dp = $p2 - $p1;
        $dl = deg2rad($lon2 - $lon1);
        $a = sin($dp / 2) ** 2 + cos($p1) * cos($p2) * sin($dl / 2) ** 2;
        return 2 * $r * asin(sqrt($a));
    }
}
