# Security Policy

WeChat AI Memory handles private local data. Security and privacy regressions
are treated as high-priority issues.

## Reporting

Use GitHub's private vulnerability reporting feature when it is enabled for
the repository. Do not open a public issue containing chat content, database
files, account identifiers, memory keys, screenshots with personal data, or
exported archives.

Include the application version, Windows and WeChat versions, reproduction
steps using synthetic data, and the expected security boundary.

## Data Boundary

The application is read-only with respect to WeChat data. Database and image
keys remain in process memory, decrypted working copies use the system temp
directory, and no telemetry or remote AI API is used by default.
