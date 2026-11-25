<?php
/**
 * Lookup for the generated texts (Translations.php). Falls back to Turkish, then to the key itself,
 * the same as services/i18n.py t().
 */

declare(strict_types=1);

namespace Farmedia;

final class Translate
{
    /** @param array<string, scalar> $params */
    public static function t(string $lang, string $key, array $params = []): string
    {
        $lang = strtolower($lang) === 'en' ? 'en' : 'tr';
        $template = Translations::TEXT[$lang][$key] ?? Translations::TEXT['tr'][$key] ?? $key;
        $map = [];
        foreach ($params as $name => $value) {
            $map['{' . $name . '}'] = (string) $value;
        }
        return strtr($template, $map);
    }
}
