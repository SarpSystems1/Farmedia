<?php
/**
 * Account registration. Port of services/accounts.py (register, validation, current_documents).
 *
 * Differences from the Supabase version, on purpose
 *   * The sign-up trigger is replaced by one transaction here: users, profiles and consent_log are
 *     written together or not at all.
 *   * Passwords are hashed with password_hash() (Argon2id when available, otherwise bcrypt).
 *   * A duplicate e-mail gets the same response as a new sign-up, so the endpoint does not reveal
 *     which addresses are registered. No second account is created.
 *   * Sessions and e-mail confirmation are NOT implemented yet. A new account always returns
 *     confirmation_required = true and session = null.
 */

declare(strict_types=1);

namespace Farmedia;

use PDO;
use PDOException;

final class Accounts
{
    public const PASSWORD_MIN = 6;     // the product rule, same as the Python version
    public const PASSWORD_MAX = 128;

    private const EMAIL_RE = '/^[^\s@]+@[^\s@]+\.[^\s@]+$/u';

    /**
     * Creates an account. Input is the decoded JSON body of POST /api/auth/register.
     *
     * @param array<string, mixed> $in
     * @return array<string, mixed>
     */
    public static function register(array $in): array
    {
        $email = self::normalizeEmail(self::text($in, 'email', 254));
        $password = self::text($in, 'password', self::PASSWORD_MAX);
        self::validatePassword($password);
        $firstName = self::name(self::text($in, 'first_name', 60), 'first_name');
        $lastName = self::name(self::text($in, 'last_name', 60), 'last_name');
        $country = self::country(self::text($in, 'country', 2));
        $locale = Compliance::normalizeLocale(self::text($in, 'locale', 8, 'en'));
        $termsVersion = self::text($in, 'terms_version', 32);
        $privacyVersion = self::text($in, 'privacy_version', 32);

        $reqs = Compliance::requirementsFor($country);
        $consents = [
            Compliance::TERMS           => self::flag($in, 'terms_accepted'),
            Compliance::PRIVACY         => self::flag($in, 'privacy_accepted'),
            Compliance::KVKK_EXPLICIT   => self::flag($in, 'kvkk_explicit'),
            Compliance::KVKK_TRANSFER   => self::flag($in, 'kvkk_transfer'),
            Compliance::ALERT_EMAIL     => self::flag($in, 'alert_email'),
            Compliance::ALERT_SMS       => self::flag($in, 'alert_sms'),
            Compliance::MARKETING_EMAIL => self::flag($in, 'marketing_email'),
            Compliance::DO_NOT_SELL     => self::flag($in, 'do_not_sell'),
        ];

        $missing = array_values(array_filter(
            $reqs['required'],
            static fn (string $consent): bool => $consents[$consent] !== true
        ));
        if ($missing !== []) {
            throw ApiException::consentRequired('Required consent not given: ' . implode(', ', $missing));
        }

        $docs = self::currentDocuments($locale);
        if (!isset($docs['terms'], $docs['privacy'])) {
            throw ApiException::notConfigured('Legal documents have not been published yet.');
        }
        if ($termsVersion !== $docs['terms']['version'] || $privacyVersion !== $docs['privacy']['version']) {
            throw ApiException::consentRequired(
                'Please review the latest Terms of Service and Privacy Policy.',
                'error.outdated_documents'
            );
        }

        $userId = self::uuid();
        $now = gmdate('Y-m-d H:i:s');
        $isKvkk = $reqs['jurisdiction'] === 'kvkk';
        $kvkkAt = $isKvkk ? $now : null;
        $passwordHash = password_hash($password, self::hashAlgorithm(), self::hashOptions());

        try {
            Database::transaction(static function (PDO $pdo) use (
                $userId, $email, $passwordHash, $firstName, $lastName, $country, $reqs, $locale,
                $docs, $consents, $isKvkk, $kvkkAt, $now
            ): void {
                self::insert($pdo, 'users', [
                    'id'            => $userId,
                    'email'         => $email,
                    'password_hash' => $passwordHash,
                    'created_at'    => $now,
                    'updated_at'    => $now,
                ]);

                self::insert($pdo, 'profiles', [
                    'user_id'                  => $userId,
                    'first_name'               => $firstName,
                    'last_name'                => $lastName,
                    'role'                     => 'hobby',
                    'location'                 => '{}',
                    'crops'                    => '{}',
                    'preferences'              => '{}',
                    'country'                  => $country,
                    'jurisdiction'             => $reqs['jurisdiction'],
                    'locale'                   => $locale,
                    'terms_version'            => $docs['terms']['version'],
                    'terms_accepted_at'        => $now,
                    'privacy_version'          => $docs['privacy']['version'],
                    'privacy_accepted_at'      => $now,
                    'kvkk_explicit_at'         => $kvkkAt,
                    'kvkk_transfer_at'         => $kvkkAt,
                    'alert_email_consent'      => (int) $consents[Compliance::ALERT_EMAIL],
                    'alert_sms_consent'        => (int) $consents[Compliance::ALERT_SMS],
                    'marketing_email_consent'  => (int) $consents[Compliance::MARKETING_EMAIL],
                    'alert_consent_updated_at' => $now,
                    'do_not_sell'              => (int) $consents[Compliance::DO_NOT_SELL],
                    'created_at'               => $now,
                    'updated_at'               => $now,
                ]);

                // Consent history, one row per consent. Terms and privacy rows carry the version.
                $rows = [
                    [Compliance::TERMS, 1, $docs['terms']['version']],
                    [Compliance::PRIVACY, 1, $docs['privacy']['version']],
                    [Compliance::ALERT_EMAIL, (int) $consents[Compliance::ALERT_EMAIL], null],
                    [Compliance::ALERT_SMS, (int) $consents[Compliance::ALERT_SMS], null],
                    [Compliance::MARKETING_EMAIL, (int) $consents[Compliance::MARKETING_EMAIL], null],
                    [Compliance::DO_NOT_SELL, (int) $consents[Compliance::DO_NOT_SELL], null],
                ];
                if ($isKvkk) {
                    $rows[] = [Compliance::KVKK_EXPLICIT, 1, $docs['privacy']['version']];
                    $rows[] = [Compliance::KVKK_TRANSFER, 1, $docs['privacy']['version']];
                }

                $log = $pdo->prepare(
                    'INSERT INTO consent_log (user_id, consent_type, granted, version, recorded_at)
                     VALUES (?, ?, ?, ?, ?)'
                );
                foreach ($rows as [$type, $granted, $version]) {
                    $log->execute([$userId, $type, $granted, $version, $now]);
                }
            });
        } catch (PDOException $e) {
            if (self::isDuplicateKey($e)) {
                // Same shape as a new sign-up that awaits confirmation. Nothing was created.
                return [
                    'user' => null,
                    'jurisdiction' => $reqs['jurisdiction'],
                    'session' => null,
                    'confirmation_required' => true,
                ];
            }
            throw $e;
        }

        return [
            'user' => ['id' => $userId, 'email' => $email],
            'jurisdiction' => $reqs['jurisdiction'],
            'session' => null,
            'confirmation_required' => true,
        ];
    }

    /**
     * The currently published Terms and Privacy Policy for a locale.
     *
     * @return array<string, array{version: string, url: string}>
     */
    public static function currentDocuments(string $locale): array
    {
        $stmt = Database::connection()->prepare(
            'SELECT doc_type, version, url FROM legal_documents WHERE is_current = 1 AND locale = ?'
        );
        $stmt->execute([$locale]);

        $docs = [];
        foreach ($stmt->fetchAll() as $row) {
            $docs[$row['doc_type']] = ['version' => $row['version'], 'url' => $row['url']];
        }
        return $docs;
    }

    public static function normalizeEmail(string $email): string
    {
        $email = mb_strtolower(trim($email), 'UTF-8');
        if (mb_strlen($email, 'UTF-8') > 254 || preg_match(self::EMAIL_RE, $email) !== 1) {
            throw ApiException::invalidInput('email', 'Enter a valid email address.');
        }
        return $email;
    }

    public static function validatePassword(string $password): void
    {
        $length = mb_strlen($password, 'UTF-8');
        if ($length < self::PASSWORD_MIN || $length > self::PASSWORD_MAX) {
            throw ApiException::invalidInput(
                'password',
                sprintf('Password must be %d to %d characters.', self::PASSWORD_MIN, self::PASSWORD_MAX)
            );
        }
        // bcrypt ignores everything after 72 bytes. Argon2id has no such limit.
        if (!defined('PASSWORD_ARGON2ID') && strlen($password) > 72) {
            throw ApiException::invalidInput('password', 'Password is longer than 72 bytes on this server.');
        }
    }

    // ---------- sessions: login, refresh, logout, current user ----------

    /** Access token lifetime, in seconds. */
    public const ACCESS_TTL = 3600;
    /** Refresh token lifetime, in seconds (30 days). */
    public const REFRESH_TTL = 2592000;

    /**
     * Signs in with e-mail and password and opens a session on this device.
     *
     * @return array{session: array<string, mixed>, user: array{id: string, email: string}}
     */
    public static function login(string $email, string $password): array
    {
        $email = self::normalizeEmail($email);
        if ($password === '') {
            throw ApiException::invalidInput('password', 'Password is required.');
        }
        if (mb_strlen($password, 'UTF-8') > self::PASSWORD_MAX) {
            throw ApiException::invalidInput('password', 'Password is too long.');
        }

        $stmt = Database::connection()->prepare(
            'SELECT id, email, password_hash, email_verified_at FROM users WHERE email = ? LIMIT 1'
        );
        $stmt->execute([$email]);
        $user = $stmt->fetch() ?: null;

        // One password check runs even for an unknown e-mail, so the response time does not show
        // which addresses have accounts.
        $valid = password_verify($password, $user['password_hash'] ?? self::dummyHash());
        if ($user === null || !$valid) {
            throw ApiException::authFailed();
        }
        // The password is checked before this, so an unconfirmed address reveals nothing to a stranger.
        if (self::requireEmailConfirmation() && $user['email_verified_at'] === null) {
            throw ApiException::emailNotConfirmed();
        }

        if (password_needs_rehash($user['password_hash'], self::hashAlgorithm(), self::hashOptions())) {
            Database::connection()->prepare('UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?')
                ->execute([password_hash($password, self::hashAlgorithm(), self::hashOptions()), gmdate('Y-m-d H:i:s'), $user['id']]);
        }

        $tokens = self::newTokens();
        Database::connection()->prepare(
            'INSERT INTO sessions (user_id, access_hash, access_expires_at, refresh_hash, refresh_expires_at, created_at)
             VALUES (?, ?, ?, ?, ?, ?)'
        )->execute(self::sessionRow($user['id'], $tokens));

        return [
            'session' => self::publicSession($tokens),
            'user' => ['id' => $user['id'], 'email' => $user['email']],
        ];
    }

    /**
     * Trades a refresh token for a new access token and a new refresh token. The old refresh token
     * stops working at once (rotation). The row is locked, so two refreshes cannot both succeed.
     *
     * @return array{session: array<string, mixed>, user: array{id: string, email: string}}
     */
    public static function refresh_session(string $refreshToken): array
    {
        if (!self::isToken($refreshToken)) {
            throw ApiException::authFailed();
        }

        return Database::transaction(static function (PDO $pdo) use ($refreshToken): array {
            $stmt = $pdo->prepare(
                'SELECT s.id, s.user_id, u.email
                   FROM sessions s JOIN users u ON u.id = s.user_id
                  WHERE s.refresh_hash = ? AND s.revoked_at IS NULL AND s.refresh_expires_at > ?
                  FOR UPDATE'
            );
            $stmt->execute([hash('sha256', $refreshToken), gmdate('Y-m-d H:i:s')]);
            $row = $stmt->fetch();
            if (!$row) {
                throw ApiException::authFailed();
            }

            $tokens = self::newTokens();
            [$userId, $accessHash, $accessExpires, $refreshHash, $refreshExpires] = self::sessionRow($row['user_id'], $tokens);
            $pdo->prepare(
                'UPDATE sessions SET access_hash = ?, access_expires_at = ?, refresh_hash = ?, refresh_expires_at = ?
                  WHERE id = ?'
            )->execute([$accessHash, $accessExpires, $refreshHash, $refreshExpires, $row['id']]);

            return [
                'session' => self::publicSession($tokens),
                'user' => ['id' => $row['user_id'], 'email' => $row['email']],
            ];
        });
    }

    /** Ends this session only. Other devices stay signed in. Calling it twice is harmless. */
    public static function logout(string $accessToken): void
    {
        if (!self::isToken($accessToken)) {
            return;
        }
        Database::connection()->prepare(
            'UPDATE sessions SET revoked_at = ? WHERE access_hash = ? AND revoked_at IS NULL'
        )->execute([gmdate('Y-m-d H:i:s'), hash('sha256', $accessToken)]);
    }

    /**
     * The signed-in user and their profile, for a valid, unexpired access token.
     *
     * @return array{user: array{id: string, email: string}, profile: array<string, mixed>|null}
     */
    public static function get_current_user(string $token): array
    {
        $user = self::authenticate($token);
        return ['user' => $user, 'profile' => self::profileRow($user['id'])];
    }

    /**
     * The user that owns a valid, unexpired, unrevoked access token. Every account operation takes
     * its user id from here, never from the request body, so a client can only touch its own rows.
     *
     * @return array{id: string, email: string}
     */
    public static function authenticate(string $token): array
    {
        if (!self::isToken($token)) {
            throw ApiException::authFailed();
        }
        $stmt = Database::connection()->prepare(
            'SELECT s.user_id, u.email
               FROM sessions s JOIN users u ON u.id = s.user_id
              WHERE s.access_hash = ? AND s.revoked_at IS NULL AND s.access_expires_at > ?'
        );
        $stmt->execute([hash('sha256', $token), gmdate('Y-m-d H:i:s')]);
        $row = $stmt->fetch();
        if (!$row) {
            throw ApiException::authFailed();
        }
        return ['id' => $row['user_id'], 'email' => $row['email']];
    }

    /** @return array<string, mixed>|null */
    private static function profileRow(string $userId): ?array
    {
        $stmt = Database::connection()->prepare('SELECT * FROM profiles WHERE user_id = ?');
        $stmt->execute([$userId]);
        $row = $stmt->fetch();
        return $row === false ? null : self::decodeProfile($row);
    }

    // ---------- legal requirements ----------

    /**
     * What the sign-up form must show for a country and language: the consents the law needs, the
     * optional ones, and the currently published documents. Port of accounts.legal_requirements.
     *
     * @return array<string, mixed>
     */
    public static function legalRequirements(string $country, ?string $locale): array
    {
        $code = self::country($country);
        $loc = Compliance::normalizeLocale($locale);
        $reqs = Compliance::requirementsFor($code);
        $docs = self::currentDocuments($loc);

        return [
            'country' => $code,
            'jurisdiction' => $reqs['jurisdiction'],
            'locale' => $loc,
            'required_consents' => $reqs['required'],
            'optional_consents' => $reqs['optional'],
            'documents' => $docs,
            'ready' => isset($docs['terms'], $docs['privacy']),
        ];
    }

    // ---------- profile ----------

    /** Fields a user may change, and the consent type each optional consent logs under. */
    private const PROFILE_FIELDS = ['first_name', 'last_name', 'role', 'farm_size', 'location', 'crops', 'preferences'];
    private const CONSENT_FIELDS = [
        'alert_email_consent' => 'alert_email',
        'alert_sms_consent' => 'alert_sms',
        'marketing_email_consent' => 'marketing_email',
        'do_not_sell' => 'do_not_sell',
    ];
    /** UI preferences that follow the user across devices. Anything else is refused. */
    private const PREFERENCE_VALUES = [
        'theme' => ['system', 'light', 'dark'],
        'density' => ['comfortable', 'compact'],
        'forecastDays' => [3, 5, 7],
    ];
    private const JSON_FIELD_MAX_BYTES = 4000;

    /** The signed-in user's profile row, or null. */
    public static function getProfile(string $token): ?array
    {
        return self::profileRow(self::authenticate($token)['id']);
    }

    /**
     * Partial profile update. Changed optional consents are logged in consent_log in the same
     * transaction as the profile write, so a change never happens without its audit row.
     *
     * @param array<string, mixed> $changes
     * @return array<string, mixed> the updated profile
     */
    public static function updateProfile(string $token, array $changes): array
    {
        $userId = self::authenticate($token)['id'];

        $unknown = array_diff(array_keys($changes), self::PROFILE_FIELDS, array_keys(self::CONSENT_FIELDS));
        if ($unknown !== []) {
            throw ApiException::invalidInput('body', 'Field(s) cannot be updated: ' . implode(', ', $unknown));
        }
        if ($changes === []) {
            throw ApiException::invalidInput('body', 'No fields to update.');
        }

        $values = [];
        foreach (self::CONSENT_FIELDS as $column => $type) {
            if (array_key_exists($column, $changes)) {
                if (!is_bool($changes[$column])) {
                    throw ApiException::invalidInput($column, "$column must be true or false.");
                }
                $values[$column] = $changes[$column];
            }
        }
        if (array_key_exists('first_name', $changes)) {
            $values['first_name'] = self::name(self::plainString($changes['first_name'], 'first_name'), 'first_name');
        }
        if (array_key_exists('last_name', $changes)) {
            $values['last_name'] = self::name(self::plainString($changes['last_name'], 'last_name'), 'last_name');
        }
        if (array_key_exists('role', $changes)) {
            if (!in_array($changes['role'], ['hobby', 'farm'], true)) {
                throw ApiException::invalidInput('role', 'role must be hobby or farm.');
            }
            $values['role'] = $changes['role'];
        }
        if (array_key_exists('farm_size', $changes)) {
            $size = $changes['farm_size'];
            if ($size !== null && (!is_numeric($size) || (float) $size < 0)) {
                throw ApiException::invalidInput('farm_size', 'farm_size must be zero or more.');
            }
            $values['farm_size'] = $size === null ? null : (float) $size;
        }
        foreach (['location', 'crops'] as $field) {
            if (array_key_exists($field, $changes)) {
                $values[$field] = self::jsonField($changes[$field], $field);
            }
        }
        if (array_key_exists('preferences', $changes)) {
            $values['preferences'] = self::jsonField(self::checkedPreferences($changes['preferences']), 'preferences');
        }

        return Database::transaction(static function (PDO $pdo) use ($userId, $changes, $values): array {
            $lock = $pdo->prepare('SELECT * FROM profiles WHERE user_id = ? FOR UPDATE');
            $lock->execute([$userId]);
            $current = $lock->fetch();
            if ($current === false) {
                throw ApiException::ruleViolation('Profile not found.');
            }

            $now = gmdate('Y-m-d H:i:s');
            $consentChanged = false;
            $set = [];
            $params = [];
            foreach ($values as $column => $value) {
                if (isset(self::CONSENT_FIELDS[$column])) {
                    $granted = $value ? 1 : 0;
                    if ($granted !== (int) $current[$column]) {
                        $pdo->prepare(
                            'INSERT INTO consent_log (user_id, consent_type, granted, version, recorded_at)
                             VALUES (?, ?, ?, NULL, ?)'
                        )->execute([$userId, self::CONSENT_FIELDS[$column], $granted, $now]);
                        $consentChanged = true;
                    }
                    $value = $granted;
                }
                $set[] = "$column = ?";
                $params[] = $value;
            }
            if ($consentChanged) {
                $set[] = 'alert_consent_updated_at = ?';
                $params[] = $now;
            }
            if ($set !== []) {
                $set[] = 'updated_at = ?';
                $params[] = $now;
                $params[] = $userId;
                $pdo->prepare('UPDATE profiles SET ' . implode(', ', $set) . ' WHERE user_id = ?')->execute($params);
            }

            $fresh = $pdo->prepare('SELECT * FROM profiles WHERE user_id = ?');
            $fresh->execute([$userId]);
            return self::decodeProfile($fresh->fetch());
        });
    }

    /**
     * Preferences: only the known keys with allowed values. Booleans are refused, so true is never
     * read as 1.
     *
     * @return array<string, string|int>
     */
    private static function checkedPreferences(mixed $prefs): array
    {
        if (!is_array($prefs)) {
            throw ApiException::invalidInput('preferences', 'preferences must be an object.');
        }
        $clean = [];
        foreach (self::PREFERENCE_VALUES as $key => $allowed) {
            if (!array_key_exists($key, $prefs)) {
                continue;
            }
            $value = $prefs[$key];
            if (is_bool($value) || !(is_string($value) || is_int($value)) || !in_array($value, $allowed, true)) {
                throw ApiException::invalidInput('preferences', "preferences.$key has an unsupported value.");
            }
            $clean[$key] = $value;
        }
        return $clean;
    }

    /** A JSON object column: must be an object or list, and small enough to store and show. */
    private static function jsonField(mixed $value, string $field): string
    {
        if (!is_array($value)) {
            throw ApiException::invalidInput($field, "$field must be an object.");
        }
        $json = json_encode($value === [] ? new \stdClass() : $value, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
        if (strlen($json) > self::JSON_FIELD_MAX_BYTES) {
            throw ApiException::invalidInput($field, "$field is too large.");
        }
        return $json;
    }

    private static function plainString(mixed $value, string $field): string
    {
        if (!is_string($value)) {
            throw ApiException::invalidInput($field, "$field must be a string.");
        }
        return $value;
    }

    // ---------- data rights: export and deletion ----------

    /**
     * A portable copy of the user's own data (GDPR Art. 20, CCPA, KVKK Art. 11).
     *
     * @return array<string, mixed>
     */
    public static function exportUserData(string $token): array
    {
        $user = self::authenticate($token);
        $stmt = Database::connection()->prepare(
            'SELECT consent_type, granted, version, recorded_at FROM consent_log
              WHERE user_id = ? ORDER BY recorded_at ASC, id ASC'
        );
        $stmt->execute([$user['id']]);
        $history = array_map(static fn (array $r): array => [
            'consent_type' => $r['consent_type'],
            'granted' => (bool) $r['granted'],
            'version' => $r['version'],
            'recorded_at' => $r['recorded_at'],
        ], $stmt->fetchAll());

        return [
            'format' => 'farmedia-export',
            'format_version' => 1,
            'exported_at' => gmdate('c'),
            'account' => $user,
            'profile' => self::profileRow($user['id']),
            'consent_history' => $history,
        ];
    }

    /**
     * Permanent deletion. The password is required again, so a stolen access token alone cannot
     * delete the account. Consent records stay, unlinked from the person, for the retention period.
     */
    public static function deleteAccount(string $token, string $password): void
    {
        $user = self::authenticate($token);
        if ($password === '') {
            throw ApiException::invalidInput('password', 'Password is required to delete your account.');
        }
        $stmt = Database::connection()->prepare('SELECT password_hash FROM users WHERE id = ?');
        $stmt->execute([$user['id']]);
        $hash = $stmt->fetchColumn();
        if ($hash === false || !password_verify($password, (string) $hash)) {
            throw ApiException::authFailed('The password is wrong.');
        }

        Database::transaction(static function (PDO $pdo) use ($user): void {
            // Keep the consent proof, but unlink it from the person, and set its end date.
            $pdo->prepare('UPDATE consent_log SET user_id = NULL, retention_until = ? WHERE user_id = ?')
                ->execute([gmdate('Y-m-d H:i:s', time() + 3 * 365 * 86400), $user['id']]);
            // Cascades to profiles and sessions.
            $pdo->prepare('DELETE FROM users WHERE id = ?')->execute([$user['id']]);
        });
    }

    /** Ends every session of this user, on every device. */
    public static function signOutEverywhere(string $token): void
    {
        $user = self::authenticate($token);
        Database::connection()->prepare(
            'UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL'
        )->execute([gmdate('Y-m-d H:i:s'), $user['id']]);
    }

    /** @return array{access_token: string, refresh_token: string} */
    private static function newTokens(): array
    {
        return ['access_token' => bin2hex(random_bytes(32)), 'refresh_token' => bin2hex(random_bytes(32))];
    }

    /**
     * The sessions row for a token pair. Only SHA-256 hashes are stored, so a leaked database
     * does not hand out working tokens.
     *
     * @param array{access_token: string, refresh_token: string} $tokens
     * @return list<string|int>
     */
    private static function sessionRow(string $userId, array $tokens): array
    {
        $now = time();
        return [
            $userId,
            hash('sha256', $tokens['access_token']),
            gmdate('Y-m-d H:i:s', $now + self::ACCESS_TTL),
            hash('sha256', $tokens['refresh_token']),
            gmdate('Y-m-d H:i:s', $now + self::REFRESH_TTL),
            gmdate('Y-m-d H:i:s', $now),
        ];
    }

    /** @param array{access_token: string, refresh_token: string} $tokens @return array<string, mixed> */
    private static function publicSession(array $tokens): array
    {
        return [
            'access_token' => $tokens['access_token'],
            'refresh_token' => $tokens['refresh_token'],
            'expires_in' => self::ACCESS_TTL,
            'token_type' => 'bearer',
        ];
    }

    /** Tokens are 64 hex characters. Anything else is rejected before it reaches the database. */
    private static function isToken(string $token): bool
    {
        return preg_match('/^[0-9a-f]{64}$/', $token) === 1;
    }

    /** @param array<string, mixed> $row @return array<string, mixed> */
    private static function decodeProfile(array $row): array
    {
        foreach (['location', 'crops', 'preferences'] as $column) {
            $row[$column] = json_decode((string) $row[$column], true) ?? new \stdClass();
        }
        foreach (['alert_email_consent', 'alert_sms_consent', 'marketing_email_consent', 'do_not_sell'] as $column) {
            $row[$column] = (bool) $row[$column];
        }
        $row['farm_size'] = $row['farm_size'] === null ? null : (float) $row['farm_size'];
        return $row;
    }

    /** Whether sign-in needs a confirmed e-mail. Confirmation mail is not sent yet, so see .env.example. */
    private static function requireEmailConfirmation(): bool
    {
        return strtolower(trim(Env::get('AUTH_REQUIRE_EMAIL_CONFIRMATION', 'true'))) !== 'false';
    }

    /** A real hash of a random string, checked when the e-mail is unknown (see login). */
    private static function dummyHash(): string
    {
        static $hash = null;
        return $hash ??= password_hash(bin2hex(random_bytes(16)), self::hashAlgorithm(), self::hashOptions());
    }

    /** @param array<string, mixed> $in */
    private static function text(array $in, string $field, int $maxLength, ?string $default = null): string
    {
        return Api::string($in, $field, $maxLength, $default);
    }

    /**
     * A consent flag. Absent means false. Present must be a real JSON boolean, so "false" or 1
     * can never count as a yes.
     *
     * @param array<string, mixed> $in
     */
    private static function flag(array $in, string $field): bool
    {
        if (!array_key_exists($field, $in)) {
            return false;
        }
        if (!is_bool($in[$field])) {
            throw ApiException::invalidInput($field, "$field must be true or false.");
        }
        return $in[$field];
    }

    private static function name(string $value, string $field): string
    {
        $value = trim($value);
        $length = mb_strlen($value, 'UTF-8');
        if ($length < 1 || $length > 60) {
            throw ApiException::invalidInput($field, "$field must be 1 to 60 characters.");
        }
        return $value;
    }

    private static function country(string $value): string
    {
        $code = strtoupper(trim($value));
        if (strlen($code) !== 2 || !ctype_alpha($code)) {
            throw ApiException::invalidInput('country', 'Country must be a 2-letter ISO code, e.g. TR or US.');
        }
        return $code;
    }

    /** @param array<string, scalar|null> $row column => value. Column names come from this file only. */
    private static function insert(PDO $pdo, string $table, array $row): void
    {
        $columns = implode(', ', array_keys($row));
        $marks = implode(', ', array_fill(0, count($row), '?'));
        $pdo->prepare("INSERT INTO $table ($columns) VALUES ($marks)")->execute(array_values($row));
    }

    private static function isDuplicateKey(PDOException $e): bool
    {
        return (int) ($e->errorInfo[1] ?? 0) === 1062; // ER_DUP_ENTRY
    }

    private static function hashAlgorithm(): string
    {
        return defined('PASSWORD_ARGON2ID') ? PASSWORD_ARGON2ID : PASSWORD_BCRYPT;
    }

    /** @return array<string, int> */
    private static function hashOptions(): array
    {
        return defined('PASSWORD_ARGON2ID') ? [] : ['cost' => 12];
    }

    /** A random UUID v4, as Supabase used for user ids. */
    private static function uuid(): string
    {
        $bytes = random_bytes(16);
        $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
        $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($bytes), 4));
    }
}
