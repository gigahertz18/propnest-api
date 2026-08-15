# PropNest Backend — Testing

## 19. Testing Architecture

The backend testing strategy should maintain a distinction between:

### Unit tests

Test:

- services
- repository behavior where practical
- business rules
- authorization decisions
- error conditions

Dependencies should be mocked or isolated where useful.

### Integration tests

Exercise:

```text
FastAPI route
    +
real application services
    +
real repository layer
    +
test PostgreSQL
```

These tests verify that the layers work together.

### End-to-end tests

Use the full running application stack where high-value user journeys need verification.

The test strategy should remain intentional rather than trying to force every behavior into a single test category.

---


## 20. Test Database Safety

Tests must never accidentally operate against a real development/production database.

The project has already introduced environment-specific configuration and guards around test execution.

The desired invariant is:

```text
ENV=unittest
    |
    v
test configuration
    |
    v
isolated database
```

A test command should fail fast if it detects an unsafe database configuration.

---

