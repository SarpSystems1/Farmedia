<?php
/**
 * Legal-compliance rules: jurisdiction from country, and which consents each jurisdiction needs.
 * Port of services/compliance.py. It mirrors public.jurisdiction_for in the old Supabase schema.
 *
 * This is an engineering mapping of publicly known rules (KVKK, GDPR, CCPA). It is not legal
 * advice. The wording of the documents and the final consent set must be approved by counsel.
 */

declare(strict_types=1);

namespace Farmedia;

final class Compliance
{
    public const TERMS = 'terms';
    public const PRIVACY = 'privacy_policy';
    public const KVKK_EXPLICIT = 'kvkk_explicit';
    public const KVKK_TRANSFER = 'kvkk_transfer';
    public const ALERT_EMAIL = 'alert_email';
    public const ALERT_SMS = 'alert_sms';
    public const MARKETING_EMAIL = 'marketing_email';
    public const DO_NOT_SELL = 'do_not_sell';

    public const LOCALES = ['tr', 'en'];

    /** EU-27, EEA extras and the UK. */
    private const GDPR_COUNTRIES = [
        'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU', 'IE',
        'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
        'IS', 'LI', 'NO', 'GB',
    ];

    public static function jurisdictionFor(string $country): string
    {
        $code = strtoupper(trim($country));
        if ($code === 'TR') {
            return 'kvkk';
        }
        if (in_array($code, self::GDPR_COUNTRIES, true)) {
            return 'gdpr';
        }
        if ($code === 'US') { // CCPA applies to California residents. US-wide is the conservative choice.
            return 'ccpa';
        }
        return 'global';
    }

    /**
     * @return array{jurisdiction: string, required: list<string>, optional: list<string>}
     *         required: must be accepted (true) to register. optional: default off.
     */
    public static function requirementsFor(string $country): array
    {
        $jurisdiction = self::jurisdictionFor($country);

        $required = [self::TERMS, self::PRIVACY];
        if ($jurisdiction === 'kvkk') {
            array_push($required, self::KVKK_EXPLICIT, self::KVKK_TRANSFER);
        }

        $optional = [self::ALERT_EMAIL, self::ALERT_SMS, self::MARKETING_EMAIL];
        if ($jurisdiction === 'ccpa') {
            $optional[] = self::DO_NOT_SELL; // opt-out switch, off by default
        }

        return ['jurisdiction' => $jurisdiction, 'required' => $required, 'optional' => $optional];
    }

    public static function normalizeLocale(?string $locale): string
    {
        return in_array($locale, self::LOCALES, true) ? (string) $locale : 'en';
    }
}
