<?php
/**
 * Crop knowledge base and free-text crop parser (Turkish and English).
 * Port of services/crops.py. The fuzzy match mirrors Python's difflib.get_close_matches.
 */

declare(strict_types=1);

namespace Farmedia;

final class Crops
{
    /**
     * [id, tr, en, family, frost_c, heat_c, water, extra aliases]
     * frost_c: air temperature at or below which damage is likely. heat_c: daily max above which heat stress is likely.
     */
    private const RAW = [
        ['wheat', 'Buğday', 'Wheat', 'cereal', -10, 35, 'medium', []],
        ['barley', 'Arpa', 'Barley', 'cereal', -10, 35, 'low', []],
        ['corn', 'Mısır', 'Corn', 'cereal', 1, 36, 'high', ['maize']],
        ['rice', 'Çeltik', 'Rice', 'cereal', 5, 35, 'high', ['pirinç', 'pirinc']],
        ['oat', 'Yulaf', 'Oat', 'cereal', -8, 32, 'medium', ['oats']],
        ['sunflower', 'Ayçiçeği', 'Sunflower', 'sunflower', -1, 35, 'medium', ['aycicegi']],
        ['cotton', 'Pamuk', 'Cotton', 'mallow', 2, 38, 'high', []],
        ['tomato', 'Domates', 'Tomato', 'nightshade', 1, 34, 'high', ['tomatoes']],
        ['pepper', 'Biber', 'Pepper', 'nightshade', 1, 34, 'medium', ['peppers', 'chili', 'capsicum']],
        ['eggplant', 'Patlıcan', 'Eggplant', 'nightshade', 2, 35, 'high', ['aubergine']],
        ['potato', 'Patates', 'Potato', 'nightshade', 0, 30, 'high', ['potatoes']],
        ['tobacco', 'Tütün', 'Tobacco', 'nightshade', 2, 35, 'medium', []],
        ['cucumber', 'Salatalık', 'Cucumber', 'cucurbit', 1, 34, 'high', ['hiyar']],
        ['watermelon', 'Karpuz', 'Watermelon', 'cucurbit', 1, 38, 'medium', []],
        ['melon', 'Kavun', 'Melon', 'cucurbit', 1, 38, 'medium', []],
        ['zucchini', 'Kabak', 'Zucchini', 'cucurbit', 1, 34, 'high', ['squash', 'pumpkin', 'balkabağı']],
        ['lettuce', 'Marul', 'Lettuce', 'aster', -2, 28, 'medium', ['salata']],
        ['spinach', 'Ispanak', 'Spinach', 'amaranth', -6, 28, 'medium', []],
        ['onion', 'Soğan', 'Onion', 'allium', -5, 32, 'medium', ['onions']],
        ['garlic', 'Sarımsak', 'Garlic', 'allium', -8, 32, 'low', []],
        ['carrot', 'Havuç', 'Carrot', 'umbellifer', -3, 32, 'medium', ['carrots']],
        ['cabbage', 'Lahana', 'Cabbage', 'brassica', -5, 30, 'medium', []],
        ['broccoli', 'Brokoli', 'Broccoli', 'brassica', -3, 30, 'medium', []],
        ['cauliflower', 'Karnabahar', 'Cauliflower', 'brassica', -2, 28, 'medium', []],
        ['bean', 'Fasulye', 'Bean', 'legume', 1, 32, 'medium', ['beans', 'taze fasulye']],
        ['pea', 'Bezelye', 'Pea', 'legume', -3, 28, 'medium', ['peas']],
        ['chickpea', 'Nohut', 'Chickpea', 'legume', -8, 35, 'low', ['chickpeas']],
        ['lentil', 'Mercimek', 'Lentil', 'legume', -8, 35, 'low', ['lentils']],
        ['alfalfa', 'Yonca', 'Alfalfa', 'legume', -8, 35, 'medium', ['lucerne']],
        ['sugarbeet', 'Şeker Pancarı', 'Sugar Beet', 'beet', -3, 35, 'medium', ['pancar', 'sugar beet']],
        ['olive', 'Zeytin', 'Olive', 'tree-olive', -7, 40, 'low', ['olives']],
        ['grape', 'Üzüm', 'Grape', 'vine', -1, 40, 'low', ['bağ', 'grapes', 'vineyard', 'asma']],
        ['apple', 'Elma', 'Apple', 'rosaceae', -2, 35, 'medium', ['apples']],
        ['pear', 'Armut', 'Pear', 'rosaceae', -2, 35, 'medium', ['pears']],
        ['cherry', 'Kiraz', 'Cherry', 'rosaceae', -2, 35, 'medium', ['cherries', 'vişne', 'visne']],
        ['peach', 'Şeftali', 'Peach', 'rosaceae', -2, 36, 'medium', ['peaches', 'nectarine', 'nektarin']],
        ['apricot', 'Kayısı', 'Apricot', 'rosaceae', -1.5, 38, 'low', ['apricots', 'kayisi']],
        ['plum', 'Erik', 'Plum', 'rosaceae', -2, 36, 'medium', ['plums']],
        ['almond', 'Badem', 'Almond', 'rosaceae', -1.5, 38, 'low', ['almonds']],
        ['strawberry', 'Çilek', 'Strawberry', 'rosaceae', -2, 30, 'high', ['strawberries']],
        ['hazelnut', 'Fındık', 'Hazelnut', 'birch', -3, 35, 'medium', ['hazelnuts', 'findik']],
        ['walnut', 'Ceviz', 'Walnut', 'walnut', -2, 38, 'medium', ['walnuts']],
        ['pistachio', 'Antep Fıstığı', 'Pistachio', 'cashew', -3, 40, 'low', ['fıstık', 'pistachios']],
        ['fig', 'İncir', 'Fig', 'mulberry', -4, 40, 'low', ['figs']],
        ['pomegranate', 'Nar', 'Pomegranate', 'loosestrife', -5, 40, 'low', ['pomegranates']],
        ['orange', 'Portakal', 'Orange', 'citrus', -2, 38, 'high', ['oranges', 'narenciye', 'citrus']],
        ['lemon', 'Limon', 'Lemon', 'citrus', -2, 38, 'high', ['lemons']],
        ['mandarin', 'Mandalina', 'Mandarin', 'citrus', -2, 38, 'high', ['mandarins', 'tangerine']],
        ['pomelo', 'Altıntopak', 'Pomelo', 'citrus', -2, 38, 'medium',
            ['pummelo', 'altintopak', 'altın topak', 'altin topak']],
        ['tea', 'Çay', 'Tea', 'tea', -2, 35, 'high', []],
        ['mint', 'Nane', 'Mint', 'mint', 0, 32, 'medium', []],
        ['basil', 'Fesleğen', 'Basil', 'mint', 2, 32, 'medium', ['feslegen']],
        ['dragonfruit', 'Ejder Meyvesi', 'Dragon Fruit', 'cactus', 2, 40, 'low',
            ['pitaya', 'pitahaya', 'ejdermeyvesi', 'dragon fruit', 'dragonfruit', 'pitaya meyvesi']],
        ['passionfruit', 'Çarkıfelek', 'Passion Fruit', 'passionflower', 3, 34, 'medium',
            ['carkifelek', 'markisa', 'maracuja', 'maracuya', 'passiflora', 'pasiflora',
                'passion fruit', 'passionfruit', 'passion flower']],
        ['mango', 'Mango', 'Mango', 'sumac', 5, 40, 'medium', ['mangos', 'mangoes']],
        ['avocado', 'Avokado', 'Avocado', 'laurel', 0, 36, 'high', ['avocados', 'avokado']],
        ['banana', 'Muz', 'Banana', 'banana', 5, 38, 'high', ['bananas', 'muzlar']],
        ['guava', 'Guava', 'Guava', 'myrtle', 2, 38, 'medium', ['guavas', 'guava meyvesi']],
        ['pineapple', 'Ananas', 'Pineapple', 'bromeliad', 2, 36, 'low', ['pineapples', 'ananas meyvesi']],
    ];

    private const NOISE = '/\d+(?:[.,]\d+)?|\b(?:donum|da|dekar|decare|decares|dunam|ha|hektar|hectare|acre|'
        . 'adet|tane|agaci|agac|bahcesi|tarlasi|ekimi|ekili|ektim|ektik|diktim|'
        . 'planted|field|orchard|trees|tree|of|the|bir)\b|[()%.:\-]/u';

    /** @var array<string, array<string, mixed>>|null id => crop */
    private static ?array $crops = null;
    /** @var array<string, string>|null normalized alias => crop id */
    private static ?array $aliases = null;

    /** @return array<string, array<string, mixed>> */
    public static function all(): array
    {
        self::boot();
        return self::$crops;
    }

    /**
     * Parses a free-text crop list into recognised crops and unrecognised leftovers.
     *
     * @return array{crops: list<array<string, mixed>>, unknown: list<string>}
     */
    public static function parse(?string $text, string $lang = 'tr'): array
    {
        self::boot();
        $recognized = [];
        $unknown = [];
        $seen = [];
        if ($text === null || $text === '') {
            return ['crops' => $recognized, 'unknown' => $unknown];
        }

        foreach (preg_split('/[,;\n\/+&|]+|\s+(?:ve|and|ile|with)\s+/iu', $text) ?: [] as $piece) {
            $raw = trim($piece);
            if ($raw === '') {
                continue;
            }
            $token = trim(preg_replace('/\s+/u', ' ', preg_replace(self::NOISE, ' ', self::norm($raw)) ?? '') ?? '');
            if ($token === '') {
                continue;
            }
            $cid = self::matchToken($token);
            if ($cid === null) {
                $unknown[] = $raw;
            } elseif (!isset($seen[$cid])) {
                $seen[$cid] = true;
                $c = self::$crops[$cid];
                $recognized[] = [
                    'id' => $c['id'],
                    'name' => $lang === 'tr' ? $c['tr'] : $c['en'],
                    'family' => $c['family'],
                    'frost_c' => $c['frost_c'],
                    'heat_c' => $c['heat_c'],
                    'water' => $c['water'],
                ];
            }
        }
        return ['crops' => $recognized, 'unknown' => $unknown];
    }

    /** Lower case, Turkish dotted/dotless i handled, Turkish letters folded to ASCII. */
    public static function norm(string $text): string
    {
        $text = str_replace(['İ', 'I'], ['i', 'ı'], $text);
        $text = mb_strtolower($text, 'UTF-8');
        return trim(strtr($text, [
            'ı' => 'i', 'ş' => 's', 'ğ' => 'g', 'ü' => 'u', 'ö' => 'o', 'ç' => 'c', 'â' => 'a', 'î' => 'i', 'û' => 'u',
        ]));
    }

    private static function boot(): void
    {
        if (self::$crops !== null) {
            return;
        }
        self::$crops = [];
        foreach (self::RAW as [$id, $tr, $en, $family, $frost, $heat, $water, $extra]) {
            self::$crops[$id] = [
                'id' => $id, 'tr' => $tr, 'en' => $en, 'family' => $family,
                'frost_c' => $frost, 'heat_c' => $heat, 'water' => $water, 'aliases' => $extra,
            ];
        }
        self::$aliases = [];
        foreach (self::$crops as $c) {
            foreach ([$c['tr'], $c['en'], $c['id'], ...$c['aliases']] as $name) {
                self::$aliases[self::norm($name)] = $c['id'];
            }
        }
    }

    private static function matchToken(string $token): ?string
    {
        if (isset(self::$aliases[$token])) {
            return self::$aliases[$token];
        }

        // An alias inside the token as a whole word ("kirmizi biber", "domatesler"): the longest wins.
        $bestLen = 0;
        $best = null;
        foreach (self::$aliases as $alias => $cid) {
            $len = mb_strlen($alias, 'UTF-8');
            if ($len < 3) {
                continue;
            }
            if (preg_match('/(?:^|\s)' . preg_quote($alias, '/') . '/u', $token) === 1 && $len > $bestLen) {
                $bestLen = $len;
                $best = $cid;
            }
        }
        if ($best !== null) {
            return $best;
        }

        // Typos ("domtaes", "wheet"): the closest alias to any single word, at least 0.8 similar.
        foreach (preg_split('/\s+/u', $token, -1, PREG_SPLIT_NO_EMPTY) ?: [] as $word) {
            $close = self::closeMatch($word, array_keys(self::$aliases), 0.8);
            if ($close !== null) {
                return self::$aliases[$close];
            }
        }
        return null;
    }

    /**
     * The best candidate with a similarity ratio of at least $cutoff, the way difflib does it with n=1:
     * among equal scores the larger string wins.
     *
     * @param list<string> $candidates
     */
    public static function closeMatch(string $word, array $candidates, float $cutoff): ?string
    {
        $best = null;
        $bestScore = -1.0;
        foreach ($candidates as $candidate) {
            $score = self::ratio($candidate, $word);
            if ($score < $cutoff) {
                continue;
            }
            if ($score > $bestScore || ($score === $bestScore && strcmp($candidate, (string) $best) > 0)) {
                $bestScore = $score;
                $best = $candidate;
            }
        }
        return $best;
    }

    /** difflib.SequenceMatcher(a, b).ratio(): 2 * matched characters / total characters. */
    public static function ratio(string $a, string $b): float
    {
        $x = preg_split('//u', $a, -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $y = preg_split('//u', $b, -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $total = count($x) + count($y);
        if ($total === 0) {
            return 1.0;
        }
        return 2.0 * self::matched($x, 0, count($x), $y, 0, count($y)) / $total;
    }

    /**
     * Sum of the longest matching blocks, found recursively on both sides of each block.
     *
     * @param list<string> $a
     * @param list<string> $b
     */
    private static function matched(array $a, int $alo, int $ahi, array $b, int $blo, int $bhi): int
    {
        [$i, $j, $k] = self::longestMatch($a, $alo, $ahi, $b, $blo, $bhi);
        if ($k === 0) {
            return 0;
        }
        return $k
            + self::matched($a, $alo, $i, $b, $blo, $j)
            + self::matched($a, $i + $k, $ahi, $b, $j + $k, $bhi);
    }

    /** @return array{0: int, 1: int, 2: int} start in a, start in b, length */
    private static function longestMatch(array $a, int $alo, int $ahi, array $b, int $blo, int $bhi): array
    {
        $besti = $alo;
        $bestj = $blo;
        $bestk = 0;
        for ($i = $alo; $i < $ahi; $i++) {
            for ($j = $blo; $j < $bhi; $j++) {
                $k = 0;
                while ($i + $k < $ahi && $j + $k < $bhi && $a[$i + $k] === $b[$j + $k]) {
                    $k++;
                }
                if ($k > $bestk) {
                    [$besti, $bestj, $bestk] = [$i, $j, $k];
                }
            }
        }
        return [$besti, $bestj, $bestk];
    }
}
