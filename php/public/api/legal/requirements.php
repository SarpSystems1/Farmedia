<?php
/**
 * GET /api/legal/requirements.php?country=TR&locale=tr
 * 200: {country, jurisdiction, locale, required_consents[], optional_consents[], documents{terms,privacy}, ready}
 * "ready" is false until both current documents are published, and sign-up is then disabled.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;

Api::handle(static function (): array {
    Api::requireMethod('GET');
    return Accounts::legalRequirements(
        Api::string($_GET, 'country', 2),
        Api::string($_GET, 'locale', 8, 'en')
    );
});
