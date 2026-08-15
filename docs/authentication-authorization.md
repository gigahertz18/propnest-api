# PropNest Backend — Authentication and Authorization

## 6. Authentication and Authorization

PropNest uses JWT bearer authentication.

The expected request flow is:

```text
Client
  |
  | Authorization: Bearer <JWT>
  v
FastAPI security dependency
  |
  v
JWT validation
  |
  v
current user
  |
  v
route/service authorization
```

Authentication answers:

> Who is this user?

Authorization answers:

> What is this user allowed to do?

These are deliberately separate concerns.

---


## 7. Role Model

The application currently uses roles including:

```text
admin
manager
user
```

The codebase has reusable dependencies/authorization concepts such as manager-or-above access.

The intended role hierarchy is approximately:

```text
admin
  |
  +-- manager
        |
        +-- user
```

The exact capability matrix should be maintained as a separate authorization policy rather than inferred from UI behavior.

The backend remains authoritative even when the frontend hides navigation/actions.

---


## 8. Property Ownership Model

Properties support manager assignment through `manager_id`.

This relationship is important because managers should generally operate on properties within their ownership/management scope.

A manager-aware service operation therefore follows a pattern like:

```text
current user
    |
    v
authorization check
    |
    +-- admin -> allowed
    |
    +-- manager -> allowed only for managed property
    |
    +-- user -> denied
```

A significant design issue previously identified is that property creation/update request schemas did not expose manager assignment even though the model and response represented `manager_id`.

That creates an architectural mismatch:

```text
Model supports manager assignment
        but
Request contract does not establish assignment
        therefore
Ownership is difficult to establish through the public API
```

This should be resolved deliberately rather than through test-only factories.

---

