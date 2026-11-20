-- Creates a second database used only by integration tests.
-- This script runs automatically when the Postgres container is first started
-- (docker-entrypoint-initdb.d). It is skipped on subsequent starts because
-- the data volume already exists.
CREATE DATABASE app_test;
