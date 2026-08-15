# PropNest Backend — Security

## 31. Security Design

### Authentication

JWT bearer authentication.

### Authorization

Server-side role and resource-scope enforcement.

### Passwords

Passwords must be hashed with a dedicated password hashing mechanism.

Plaintext passwords must never be persisted.

### Secrets

Secrets are configuration values, not source-controlled constants.

### File access

Document/object access should be authorized through backend policy.

A public storage URL should not automatically imply authorization to access a document.

### Input validation

All externally supplied input must be validated before use.

### SQL safety

Use SQLAlchemy parameterized expressions rather than string-built SQL.

---


Security includes authentication, authorization, secret handling, password protection, safe file access, validation, and SQL injection prevention.
