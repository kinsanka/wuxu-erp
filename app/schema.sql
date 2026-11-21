CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','planner','warehouse','clinical','viewer')), enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS partners (
  id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('vendor','customer','both')), contact TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sites (
  id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('factory','central','clinical'))
);
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('material','product','medical')),
  unit TEXT NOT NULL, minimum BIGINT NOT NULL CHECK(minimum >= 0),
  quality INTEGER NOT NULL CHECK(quality IN (0,1)), tracked INTEGER NOT NULL CHECK(tracked IN (0,1)),
  gtin TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS item_gtin_unique ON items(gtin) WHERE gtin <> '';
CREATE TABLE IF NOT EXISTS lots (
  id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id), code TEXT NOT NULL,
  expiry TEXT, status TEXT NOT NULL CHECK(status IN ('pending','released','blocked')),
  created TEXT NOT NULL, UNIQUE(item_id,code)
);
CREATE TABLE IF NOT EXISTS stock (
  lot_id TEXT NOT NULL REFERENCES lots(id), site_id TEXT NOT NULL REFERENCES sites(id),
  quantity BIGINT NOT NULL CHECK(quantity >= 0), PRIMARY KEY(lot_id,site_id)
);
CREATE TABLE IF NOT EXISTS boms (
  id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id), version TEXT NOT NULL, created TEXT NOT NULL,
  UNIQUE(item_id,version)
);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, ref TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN ('purchase','sale','work')),
  status TEXT NOT NULL CHECK(status IN ('draft','approved','partial','running','done','cancelled')),
  site_id TEXT NOT NULL REFERENCES sites(id), partner_id TEXT REFERENCES partners(id),
  bom_id TEXT REFERENCES boms(id), note TEXT NOT NULL, created TEXT NOT NULL, due TEXT
);
CREATE TABLE IF NOT EXISTS document_lines (
  id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id), item_id TEXT NOT NULL REFERENCES items(id),
  quantity BIGINT NOT NULL CHECK(quantity > 0), fulfilled BIGINT NOT NULL DEFAULT 0 CHECK(fulfilled >= 0 AND fulfilled <= quantity),
  price BIGINT NOT NULL DEFAULT 0 CHECK(price >= 0), UNIQUE(doc_id,item_id)
);
CREATE TABLE IF NOT EXISTS bom_lines (
  id TEXT PRIMARY KEY, bom_id TEXT NOT NULL REFERENCES boms(id), item_id TEXT NOT NULL REFERENCES items(id),
  quantity BIGINT NOT NULL CHECK(quantity > 0), UNIQUE(bom_id,item_id)
);
CREATE TABLE IF NOT EXISTS bom_steps (
  id TEXT PRIMARY KEY, bom_id TEXT NOT NULL REFERENCES boms(id), step_no INTEGER NOT NULL, name TEXT NOT NULL,
  UNIQUE(bom_id,step_no)
);
CREATE TABLE IF NOT EXISTS work_steps (
  doc_id TEXT NOT NULL REFERENCES documents(id), step_id TEXT NOT NULL REFERENCES bom_steps(id),
  minutes INTEGER NOT NULL CHECK(minutes >= 0), note TEXT NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL,
  PRIMARY KEY(doc_id,step_id)
);
CREATE TABLE IF NOT EXISTS work_links (
  doc_id TEXT NOT NULL REFERENCES documents(id), input_lot TEXT NOT NULL REFERENCES lots(id),
  output_lot TEXT NOT NULL REFERENCES lots(id), PRIMARY KEY(doc_id,input_lot,output_lot)
);
CREATE TABLE IF NOT EXISTS units (
  id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, serial TEXT, lot_id TEXT NOT NULL REFERENCES lots(id),
  site_id TEXT REFERENCES sites(id), status TEXT NOT NULL CHECK(status IN ('stock','used')),
  UNIQUE(lot_id,serial)
);
CREATE TABLE IF NOT EXISTS movements (
  id TEXT PRIMARY KEY, lot_id TEXT NOT NULL REFERENCES lots(id), site_id TEXT NOT NULL REFERENCES sites(id),
  quantity BIGINT NOT NULL CHECK(quantity <> 0), kind TEXT NOT NULL, ref TEXT NOT NULL,
  actor TEXT NOT NULL, created TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS movements_lot_idx ON movements(lot_id,created);
CREATE INDEX IF NOT EXISTS movements_ref_idx ON movements(ref,kind);
CREATE TABLE IF NOT EXISTS clinical (
  id TEXT PRIMARY KEY, ref TEXT NOT NULL UNIQUE, unit_id TEXT NOT NULL UNIQUE REFERENCES units(id),
  site_id TEXT NOT NULL REFERENCES sites(id), case_ref TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','confirmed','rejected')),
  billing_ref TEXT, note TEXT NOT NULL, created TEXT NOT NULL, billed TEXT
);
CREATE TABLE IF NOT EXISTS inspections (
  id TEXT PRIMARY KEY, lot_id TEXT NOT NULL REFERENCES lots(id), verdict TEXT NOT NULL, note TEXT NOT NULL,
  actor TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, ref TEXT NOT NULL,
  detail TEXT NOT NULL, created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
  user_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL, request_key TEXT NOT NULL,
  digest TEXT NOT NULL, response TEXT NOT NULL, created BIGINT NOT NULL, PRIMARY KEY(user_id,action,request_key)
);
CREATE INDEX IF NOT EXISTS idempotency_created_idx ON idempotency(created);

CREATE TABLE IF NOT EXISTS order_exercises (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  revision BIGINT NOT NULL CHECK(revision>=0),
  snapshot TEXT NOT NULL
);
