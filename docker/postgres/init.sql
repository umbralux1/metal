-- Расширения для поиска по каталогу (выполняется один раз при создании тома)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Отдельная база для тестов
CREATE DATABASE metal_test OWNER metal;
\connect metal_test
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
