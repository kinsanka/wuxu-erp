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

CREATE TABLE IF NOT EXISTS supply_links (
  demand_id TEXT NOT NULL REFERENCES documents(id), supply_id TEXT NOT NULL REFERENCES documents(id),
  created TEXT NOT NULL, PRIMARY KEY(demand_id,supply_id), CHECK(demand_id<>supply_id)
);
CREATE TABLE IF NOT EXISTS personnel (
  id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, team TEXT NOT NULL,
  active INTEGER NOT NULL CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS work_assignments (
  doc_id TEXT NOT NULL REFERENCES documents(id), step_id TEXT NOT NULL REFERENCES bom_steps(id),
  person_id TEXT NOT NULL REFERENCES personnel(id), created TEXT NOT NULL, PRIMARY KEY(doc_id,step_id)
);
CREATE TABLE IF NOT EXISTS shipments (
  id TEXT PRIMARY KEY, ref TEXT NOT NULL UNIQUE, doc_id TEXT NOT NULL REFERENCES documents(id),
  carrier TEXT NOT NULL, tracking TEXT NOT NULL, due TEXT NOT NULL, dispatched TEXT NOT NULL,
  signed TEXT, receipt TEXT, UNIQUE(carrier,tracking)
);
CREATE TABLE IF NOT EXISTS shipment_movements (
  shipment_id TEXT NOT NULL REFERENCES shipments(id), movement_id TEXT PRIMARY KEY REFERENCES movements(id)
);
CREATE TABLE IF NOT EXISTS trade_invoices (
  id TEXT PRIMARY KEY, ref TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('ar','ap')),
  doc_id TEXT NOT NULL REFERENCES documents(id),
  due TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(direction,ref)
);
CREATE TABLE IF NOT EXISTS trade_invoice_lines (
  invoice_id TEXT NOT NULL REFERENCES trade_invoices(id), line_id TEXT NOT NULL REFERENCES document_lines(id),
  quantity BIGINT NOT NULL CHECK(quantity>0), price BIGINT NOT NULL CHECK(price>=0),
  amount BIGINT NOT NULL CHECK(amount>0), PRIMARY KEY(invoice_id,line_id)
);
CREATE TABLE IF NOT EXISTS trade_settlements (
  id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES trade_invoices(id), ref TEXT NOT NULL,
  amount BIGINT NOT NULL CHECK(amount>0), created TEXT NOT NULL, UNIQUE(invoice_id,ref)
);
CREATE TABLE IF NOT EXISTS accepted_receipts (
  movement_id TEXT PRIMARY KEY REFERENCES movements(id), accepted TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_returns (
  movement_id TEXT PRIMARY KEY REFERENCES movements(id), receipt_id TEXT NOT NULL REFERENCES movements(id),
  ref TEXT NOT NULL UNIQUE, quantity BIGINT NOT NULL CHECK(quantity>0)
);
CREATE INDEX IF NOT EXISTS purchase_returns_receipt_idx ON purchase_returns(receipt_id);
CREATE TABLE IF NOT EXISTS trade_payments (
  id TEXT PRIMARY KEY, ref TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('ar','ap')),
  partner_id TEXT NOT NULL REFERENCES partners(id), amount BIGINT NOT NULL CHECK(amount>0),
  transacted TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(direction,ref)
);
CREATE TABLE IF NOT EXISTS payment_allocations (
  settlement_id TEXT PRIMARY KEY REFERENCES trade_settlements(id), payment_id TEXT NOT NULL REFERENCES trade_payments(id)
);
CREATE INDEX IF NOT EXISTS payment_allocations_payment_idx ON payment_allocations(payment_id);
CREATE TABLE IF NOT EXISTS inventory_counts (
  id TEXT PRIMARY KEY, ref TEXT NOT NULL UNIQUE, site_id TEXT NOT NULL REFERENCES sites(id),
  lot_id TEXT NOT NULL REFERENCES lots(id), book BIGINT NOT NULL CHECK(book>=0),
  counted BIGINT NOT NULL CHECK(counted>=0), reason TEXT NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS supply_links_source_idx ON supply_links(supply_id);
CREATE INDEX IF NOT EXISTS work_assignments_person_idx ON work_assignments(person_id);
CREATE INDEX IF NOT EXISTS shipments_doc_idx ON shipments(doc_id);
CREATE INDEX IF NOT EXISTS shipment_movements_shipment_idx ON shipment_movements(shipment_id);
CREATE INDEX IF NOT EXISTS trade_invoice_lines_source_idx ON trade_invoice_lines(line_id);
CREATE TABLE IF NOT EXISTS practice_runs (
  id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL REFERENCES users(id),
  site_id TEXT NOT NULL UNIQUE REFERENCES sites(id), product_id TEXT NOT NULL UNIQUE REFERENCES items(id),
  raw_id TEXT NOT NULL UNIQUE REFERENCES items(id), sale_id TEXT NOT NULL UNIQUE REFERENCES documents(id),
  purchase_id TEXT NOT NULL UNIQUE REFERENCES documents(id), work_id TEXT NOT NULL UNIQUE REFERENCES documents(id),
  created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS practice_runs_user_idx ON practice_runs(user_id,created);
