<?php
/**
 * DELETE /api/account.php  {"password": "..."}   permanently deletes the account -> 204
 * POST   /api/account.php  {"action": "sign_out_everywhere"}  ends every session of this user -> 204
 * Both need Authorization: Bearer <access_token>.
 */

declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/src/bootstrap.php';

use Farmedia\Accounts;
use Farmedia\Api;
use Farmedia\ApiException;

Api::handle(static function (): ?array {
    Api::requireMethod('DELETE', 'POST');
    $token = Api::bearerToken();

    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'DELETE') {
        $in = Api::jsonBody();
        Accounts::deleteAccount($token, Api::string($in, 'password', 128, ''));
        return null;
    }

    $in = Api::jsonBody();
    $action = Api::string($in, 'action', 32);
    if ($action !== 'sign_out_everywhere') {
        throw ApiException::invalidInput('action', 'Unknown action.');
    }
    Accounts::signOutEverywhere($token);
    return null;
});
