<?php
/**
 * Currency for the countries offered at sign-up. Port of the REGIONS table in services/regions.py.
 * Any other country has no currency, so no price is shown or guessed for it.
 */

declare(strict_types=1);

namespace Farmedia;

final class Regions
{
    /** ISO alpha-2 => [currency code, symbol, number-format locale] */
    private const CURRENCY = [
        'TR' => ['TRY', '₺', 'tr-TR'],
        'US' => ['USD', '$', 'en-US'],
        'GB' => ['GBP', '£', 'en-GB'],
        'DE' => ['EUR', '€', 'de-DE'],
        'FR' => ['EUR', '€', 'fr-FR'],
        'NL' => ['EUR', '€', 'nl-NL'],
        'ES' => ['EUR', '€', 'es-ES'],
        'IT' => ['EUR', '€', 'it-IT'],
        'PL' => ['PLN', 'zł', 'pl-PL'],
        'CA' => ['CAD', 'CA$', 'en-CA'],
        'AU' => ['AUD', 'A$', 'en-AU'],
    ];

    /** ISO alpha-2 => [Turkish name, English name]. Same list as services/regions.py. */
    private const NAMES = [
        'TR' => ['Türkiye', 'Turkey'],
        'US' => ['ABD', 'United States'],
        'GB' => ['Birleşik Krallık', 'United Kingdom'],
        'DE' => ['Almanya', 'Germany'],
        'FR' => ['Fransa', 'France'],
        'NL' => ['Hollanda', 'Netherlands'],
        'ES' => ['İspanya', 'Spain'],
        'IT' => ['İtalya', 'Italy'],
        'PL' => ['Polonya', 'Poland'],
        'CA' => ['Kanada', 'Canada'],
        'AU' => ['Avustralya', 'Australia'],
    ];

    /** Names users may have typed before country codes were stored (lower case). Same as regions.py. */
    private const NAME_TO_CODE = [
        'turkey' => 'TR', 'türkiye' => 'TR', 'turkiye' => 'TR', 'tr' => 'TR', 'türkei' => 'TR',
        'united states' => 'US', 'usa' => 'US', 'us' => 'US', 'united states of america' => 'US', 'abd' => 'US',
        'united kingdom' => 'GB', 'uk' => 'GB', 'gb' => 'GB', 'england' => 'GB', 'birleşik krallık' => 'GB',
        'germany' => 'DE', 'deutschland' => 'DE', 'de' => 'DE', 'almanya' => 'DE',
        'france' => 'FR', 'fr' => 'FR', 'fransa' => 'FR',
        'netherlands' => 'NL', 'nederland' => 'NL', 'hollanda' => 'NL', 'nl' => 'NL',
        'spain' => 'ES', 'españa' => 'ES', 'espana' => 'ES', 'es' => 'ES', 'ispanya' => 'ES', "i\u{0307}spanya" => 'ES',
        'italy' => 'IT', 'italia' => 'IT', 'it' => 'IT', 'italya' => 'IT',
        'poland' => 'PL', 'polska' => 'PL', 'pl' => 'PL', 'polonya' => 'PL',
        'canada' => 'CA', 'ca' => 'CA', 'kanada' => 'CA',
        'australia' => 'AU', 'au' => 'AU', 'avustralya' => 'AU',
    ];

    /** A known code from a typed country name, or null when unsure. */
    public static function codeFromName(?string $name): ?string
    {
        return self::NAME_TO_CODE[mb_strtolower(trim((string) $name), 'UTF-8')] ?? null;
    }

    /** The code from the client, else the code from the typed name. Unknown countries give null. */
    public static function resolve(?string $code, ?string $name = null): ?string
    {
        return self::normalize($code) ?? self::codeFromName($name);
    }

    /** The country's display name in Turkish or English, or '' for an unknown country. */
    public static function countryName(?string $code, string $lang): string
    {
        $code = strtoupper((string) $code);
        return isset(self::NAMES[$code]) ? self::NAMES[$code][$lang === 'tr' ? 0 : 1] : '';
    }

    /** The code in upper case if it is a country we know, otherwise null. */
    public static function normalize(?string $code): ?string
    {
        $code = strtoupper(trim((string) $code));
        return isset(self::CURRENCY[$code]) ? $code : null;
    }

    /** @return array{code: string, symbol: string, locale: string}|null */
    public static function currency(?string $code): ?array
    {
        $code = self::normalize($code);
        if ($code === null) {
            return null;
        }
        [$currency, $symbol, $locale] = self::CURRENCY[$code];
        return ['code' => $currency, 'symbol' => $symbol, 'locale' => $locale];
    }
}
