<?php
/**
 * User-facing messages. The Turkish and English texts are copied from services/i18n.py.
 * Keep both files in sync when a message changes.
 */

declare(strict_types=1);

namespace Farmedia;

final class Messages
{
    private const TEXT = [
        'tr' => [
            'error.internal'           => 'Beklenmeyen bir iç hata oluştu.',
            'error.invalid_input'      => 'Girilen veriler geçersiz: {field}',
            'error.consent_required'   => 'Kayıt için KVKK aydınlatma metnini onaylamanız gerekir.',
            'error.not_configured'     => 'Hizmet yapılandırması eksik. Lütfen yönetici ile iletişime geçin.',
            'error.rule_violation'     => 'İstek kurallara uymuyor. Lütfen bilgilerinizi kontrol edin.',
            'error.terms_required'     => 'Kullanım Koşulları ve Gizlilik Politikası\'nı kabul etmeniz gerekir.',
            'error.outdated_documents' => 'Lütfen en güncel Kullanım Koşulları ve Gizlilik Politikası\'nı inceleyin.',
            'error.invalid_country'    => 'Geçerli bir ülke kodu gerekli (ör. TR, US).',
            'error.registration_rejected' => 'Kayıt tamamlanamadı. Lütfen bilgilerinizi kontrol edip tekrar deneyin.',
            'error.unavailable'        => 'Hizmet şu anda kullanılamıyor. Lütfen daha sonra tekrar deneyin.',
            'error.auth_failed'        => 'E-posta veya şifre hatalı.',
            'error.upstream_failure'   => 'Harici servis bir hata döndürdü veya geçersiz yanıt verdi.',
            'error.upstream_timeout'   => 'Harici servis zamanında yanıt vermedi.',
            'error.location_not_found' => 'İstenen konum bulunamadı: {query}',
            'error.email_not_confirmed' => 'Önce e-posta adresinizi onaylayın. Gelen kutunuzdaki bağlantıya tıklayın.',
            'error.method_not_allowed' => 'Bu istek yöntemi desteklenmiyor.',
            'error.payload_too_large'  => 'İstek gövdesi çok büyük.',
        ],
        'en' => [
            'error.internal'           => 'An unexpected internal error occurred.',
            'error.invalid_input'      => 'The provided input is invalid: {field}',
            'error.consent_required'   => 'You must accept the KVKK privacy notice to create an account.',
            'error.not_configured'     => 'The service is not configured. Please contact the administrator.',
            'error.rule_violation'     => 'The request does not meet the required rules. Please check your details.',
            'error.terms_required'     => 'You must accept the Terms of Service and Privacy Policy.',
            'error.outdated_documents' => 'Please review the latest Terms of Service and Privacy Policy.',
            'error.invalid_country'    => 'A valid country code is required (e.g. TR, US).',
            'error.registration_rejected' => 'Registration could not be completed. Please check your details and try again.',
            'error.unavailable'        => 'The service is unavailable right now. Please try again later.',
            'error.auth_failed'        => 'Invalid email or password.',
            'error.upstream_failure'   => 'The upstream service returned an error or an invalid response.',
            'error.upstream_timeout'   => 'The upstream service did not respond in time.',
            'error.location_not_found' => 'The requested location could not be found: {query}',
            'error.email_not_confirmed' => 'Confirm your email address first. Check your inbox for the link.',
            'error.method_not_allowed' => 'This HTTP method is not allowed.',
            'error.payload_too_large'  => 'The request body is too large.',
        ],
    ];

    /** @param array<string, string> $params */
    public static function translate(string $lang, string $key, array $params = []): string
    {
        $lang = $lang === 'en' ? 'en' : 'tr';
        $text = self::TEXT[$lang][$key] ?? self::TEXT[$lang]['error.internal'];
        $map = [];
        foreach ($params as $name => $value) {
            if (is_scalar($value)) {
                $map['{' . $name . '}'] = (string) $value;
            }
        }
        return strtr($text, $map);
    }
}
