-- First cleaned (core) table: one row per assessor account, derived from the
-- raw PortlandMaps assessor capture in the lake. The raw file is never edited;
-- this is where derivations live. Its headline job today: give every condo
-- sub-unit (parking/garage) a real address by inheriting its parent parcel's
-- street address, so no property is addressless in the cleaned layer.
CREATE TABLE IF NOT EXISTS core_property (
  property_id       TEXT PRIMARY KEY,
  state_id          TEXT,
  parent_state_id   TEXT,
  account_status    TEXT,
  owner             TEXT,
  address           TEXT,   -- resolved: direct, or inherited from the parent
  address_source    TEXT,   -- direct | inherited | none
  unit              TEXT,   -- parsed from the legal description
  raw_address       TEXT,   -- what PortlandMaps returned (may be null)
  city              TEXT,
  state             TEXT,
  zip_code          TEXT,
  neighborhood      TEXT,
  legal_description TEXT,
  market_value      REAL,
  sale_date         TEXT,
  sale_price        REAL,
  year_built        TEXT,
  square_feet       REAL,
  latitude          REAL,
  longitude         REAL,
  captured_date     TEXT,
  source            TEXT DEFAULT 'PortlandMaps'
);
CREATE INDEX IF NOT EXISTS ix_core_property_address ON core_property (address);
CREATE INDEX IF NOT EXISTS ix_core_property_owner   ON core_property (owner);
CREATE INDEX IF NOT EXISTS ix_core_property_source  ON core_property (address_source);
