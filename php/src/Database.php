<?php
/**
 * One shared PDO connection to MySQL, plus a transaction helper.
 *
 * Security rules followed here
 *   * Every query uses prepared statements (emulation off), so user input is never concatenated into SQL.
 *   * Errors throw exceptions. Connection details and PDO messages are written to the server log only.
 */

declare(strict_types=1);

namespace Farmedia;

use PDO;
use PDOException;

final class Database
{
    private static ?PDO $pdo = null;

    public static function connection(): PDO
    {
        if (self::$pdo !== null) {
            return self::$pdo;
        }

        $name = Env::get('DB_DATABASE');
        $user = Env::get('DB_USERNAME');
        if ($name === '' || $user === '') {
            throw ApiException::notConfigured('DB_DATABASE and DB_USERNAME must be set.');
        }

        $dsn = sprintf(
            'mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4',
            Env::get('DB_HOST', '127.0.0.1'),
            (int) Env::get('DB_PORT', '3306'),
            $name
        );

        try {
            self::$pdo = new PDO($dsn, $user, Env::get('DB_PASSWORD'), [
                PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES   => false,
                PDO::ATTR_TIMEOUT            => 5,
            ]);
        } catch (PDOException $e) {
            error_log('[farmedia] database connection failed: ' . $e->getMessage());
            throw ApiException::unavailable();
        }

        return self::$pdo;
    }

    /**
     * Runs $work inside one transaction. Commits if it returns, rolls back if it throws.
     *
     * @template T
     * @param callable(PDO): T $work
     * @return T
     */
    public static function transaction(callable $work): mixed
    {
        $pdo = self::connection();
        $pdo->beginTransaction();
        try {
            $result = $work($pdo);
            $pdo->commit();
            return $result;
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }
}
