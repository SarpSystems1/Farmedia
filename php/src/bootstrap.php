<?php
/**
 * Loads the Farmedia PHP classes and the environment. Include this once from every entry point.
 *
 * No Composer is needed: classes in the Farmedia\ namespace map to php/src/<Name>.php.
 */

declare(strict_types=1);

spl_autoload_register(static function (string $class): void {
    $prefix = 'Farmedia\\';
    if (strncmp($class, $prefix, strlen($prefix)) !== 0) {
        return;
    }
    $file = __DIR__ . '/' . str_replace('\\', '/', substr($class, strlen($prefix))) . '.php';
    if (is_file($file)) {
        require $file;
    }
});

// The project-root .env (dirname of php/ is the project root). Real environment variables win.
\Farmedia\Env::load(dirname(__DIR__, 2) . '/.env');

// Every timestamp in the application is UTC.
date_default_timezone_set('UTC');
