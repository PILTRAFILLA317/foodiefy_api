-- PostgreSQL 16+ grants creator ADMIN without SET by default.
-- Permit the administrator to assume the restricted runtime role; no client grant.
grant foodiefy_import_backend to postgres with set true;
