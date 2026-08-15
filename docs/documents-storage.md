# PropNest Backend — Documents and Object Storage

## 12. Document Architecture

Documents are both:

1. database metadata
2. object storage content

A document record contains metadata such as:

- document ID
- property/contract/tenant relationship
- optional collection relationship (`collection_id`, `ON DELETE SET NULL`)
- file name
- document type
- file URL/storage reference
- timestamps

The actual file content is stored in MinIO.

---


## 13. Document Storage Key Design

A storage object key must be unique independently of the human-readable file name.

Using:

```text
file_name
```

as the storage key causes collisions when two documents have the same file name.

The correct design is to derive storage identity from a unique identifier.

For example:

```text
documents/{document_id}/{original_filename}
```

or:

```text
documents/{uuid}-{original_filename}
```

The original filename remains metadata/display information.

The storage key becomes immutable object identity.

This principle must be used consistently across:

- upload
- replace
- delete
- any restore/retry workflow

---


## 14. Document Lifecycle

Conceptual upload workflow:

```text
Request
  |
  v
Validate user/property
  |
  v
Generate document identity
  |
  v
Upload object to MinIO
  |
  v
Create document metadata
  |
  v
Commit database transaction
```

The exact failure policy must explicitly handle:

- storage upload succeeds, DB insert fails
- DB insert succeeds, storage operation fails
- replacement succeeds partially
- deletion succeeds partially

The backend should not assume these steps are atomically coupled.

---


## 11. Transaction Design

A database transaction is not equivalent to a distributed transaction.

This is especially important for documents.

For a normal database-only operation:

```text
begin
  |
  +-- repository changes
  |
commit
```

For database + MinIO:

```text
database
   +
MinIO
```

there is no inherent atomic commit across both systems.

This creates failure modes such as:

### Case A

```text
DELETE DB row
DELETE MinIO object
COMMIT DB
```

If MinIO deletion succeeds but DB commit fails:

```text
object is gone
row comes back
```

### Case B

Reverse the order and the inverse inconsistency can occur.

Therefore document/file operations require explicit failure-compensation or an architecture that tolerates eventual consistency.

---

