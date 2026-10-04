-- Demo read-only SQL target for Coia Agents
-- Idempotent / re-runnable: DROP + CREATE + reseed. Safe on an already-initialized DB.
--
-- Apply without wiping the Postgres volume:
--   python scripts/load_demo_db.py
--   # or: docker compose up demo-db-seed
--
-- First boot also runs this via docker-entrypoint-initdb.d (empty volume only).
-- Named volume demo_db_data keeps Postgres data across restarts; the seed job
-- refreshes schema/data on each compose up.
--
-- Tables: customers, products, employees, orders, order_items, sales_transactions,
--         demo_info (catalog), schema_version (loader marker)

DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS sales_transactions CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS demo_info CASCADE;
DROP TABLE IF EXISTS schema_version CASCADE;

-- ---------------------------------------------------------------------------
-- customers (40)
-- ---------------------------------------------------------------------------
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(160) NOT NULL UNIQUE,
    country VARCHAR(60) NOT NULL,
    segment VARCHAR(40) NOT NULL,
    created_at DATE NOT NULL
);

INSERT INTO customers (id, name, email, country, segment, created_at) VALUES
    (1,  'Acme Corp',            'billing@acme.example',           'USA',         'Enterprise', '2024-01-08'),
    (2,  'Brightleaf Foods',     'ops@brightleaf.example',         'Canada',      'SMB',        '2024-01-15'),
    (3,  'Nordic Analytics',     'hello@nordic-a.example',         'Sweden',      'Enterprise', '2024-01-22'),
    (4,  'Maple Retail Co',      'buy@mapleretail.example',        'Canada',      'SMB',        '2024-02-03'),
    (5,  'Sunrise Clinics',      'procurement@sunrise.example',    'USA',         'Enterprise', '2024-02-11'),
    (6,  'Harbor Logistics',     'ap@harborlog.example',           'UK',          'Enterprise', '2024-02-19'),
    (7,  'Pixel Forge Studio',   'studio@pixelforge.example',      'Germany',     'SMB',        '2024-03-01'),
    (8,  'GreenField Farms',     'orders@greenfield.example',      'Australia',   'SMB',        '2024-03-09'),
    (9,  'Atlas Manufacturing',  'purchasing@atlas-mfg.example',   'USA',         'Enterprise', '2024-03-18'),
    (10, 'Coastal Boutique',     'hello@coastalboutique.example',  'USA',         'Consumer',   '2024-03-25'),
    (11, 'Lumen Education',      'it@lumen-edu.example',           'Ireland',     'SMB',        '2024-04-02'),
    (12, 'Summit Outdoor',       'sales@summitout.example',        'Switzerland', 'SMB',        '2024-04-10'),
    (13, 'Orbit Media',          'finance@orbitmedia.example',     'UK',          'Enterprise', '2024-04-18'),
    (14, 'Cedar Health',         'supply@cedarhealth.example',     'USA',         'Enterprise', '2024-04-26'),
    (15, 'Bluewave Telecom',     'vendor@bluewave.example',        'Spain',       'Enterprise', '2024-05-04'),
    (16, 'Quiet Desk Co',        'team@quietdesk.example',         'Netherlands', 'Consumer',   '2024-05-12'),
    (17, 'Riverstone Bank',      'procurement@riverstone.example', 'USA',         'Enterprise', '2024-05-20'),
    (18, 'Foothill Markets',     'buyer@foothill.example',         'Mexico',      'SMB',        '2024-05-28'),
    (19, 'Silverline Airlines',  'opsbuy@silverline.example',      'USA',         'Enterprise', '2024-06-05'),
    (20, 'Nest & Co',            'shop@nestco.example',            'France',      'Consumer',   '2024-06-13'),
    (21, 'Ironclad Security',    'ap@ironclad.example',            'USA',         'Enterprise', '2024-06-21'),
    (22, 'Willow Schools Dist',  'tech@willowschools.example',     'Canada',      'SMB',        '2024-07-02'),
    (23, 'Cascade Brewing',      'orders@cascadebrew.example',     'USA',         'SMB',        '2024-07-14'),
    (24, 'Nova Biotech',         'lab@novabio.example',            'Germany',     'Enterprise', '2024-07-26'),
    (25, 'Pacific Yarns',        'wholesale@pacificyarns.example', 'Japan',       'SMB',        '2024-08-07'),
    (26, 'Urban Pedals',         'store@urbanpedals.example',      'Denmark',     'Consumer',   '2024-08-19'),
    (27, 'Helix Consulting',     'finance@helixc.example',         'UK',          'Enterprise', '2024-09-01'),
    (28, 'Amber Dental Group',   'office@amberdental.example',     'USA',         'SMB',        '2024-09-14'),
    (29, 'Skybridge Freight',    'buy@skybridge.example',          'Singapore',   'Enterprise', '2024-09-28'),
    (30, 'Lark Home Goods',      'hello@larkhome.example',         'USA',         'Consumer',   '2024-10-09'),
    (31, 'Quark Software',       'ops@quarksoft.example',          'Israel',      'Enterprise', '2024-10-22'),
    (32, 'Meadow Veterinary',    'clinic@meadowvet.example',       'New Zealand', 'SMB',        '2024-11-03'),
    (33, 'Polar Sports Club',    'gear@polarsports.example',       'Norway',      'Consumer',   '2024-11-17'),
    (34, 'Titanium Parts Ltd',   'purchasing@titanium.example',    'South Korea', 'Enterprise', '2024-12-01'),
    (35, 'Coral Hotels',         'procurement@coralhotels.example','Portugal',    'Enterprise', '2024-12-14'),
    (36, 'Beacon Nonprofits',    'admin@beaconnp.example',         'USA',         'SMB',        '2025-01-08'),
    (37, 'Driftwood Design',     'studio@driftwood.example',       'Italy',       'SMB',        '2025-02-11'),
    (38, 'Evergreen Energy',     'vendors@evergreen-e.example',    'USA',         'Enterprise', '2025-03-19'),
    (39, 'Mint Mobile Repair',   'parts@mintrepair.example',       'India',       'SMB',        '2025-05-02'),
    (40, 'Apex Robotics',        'supply@apexrobotics.example',    'USA',         'Enterprise', '2025-07-16');

SELECT setval(pg_get_serial_sequence('customers', 'id'), (SELECT MAX(id) FROM customers));

-- ---------------------------------------------------------------------------
-- products (16)
-- ---------------------------------------------------------------------------
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(60) NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO products (id, name, category, unit_price, active) VALUES
    (1,  'Widget A',           'Hardware',     29.99, TRUE),
    (2,  'Widget B',           'Hardware',     49.50, TRUE),
    (3,  'Gadget Pro',         'Electronics', 199.00, TRUE),
    (4,  'Gadget Lite',        'Electronics',  79.99, TRUE),
    (5,  'Service Plan',       'Services',    499.00, TRUE),
    (6,  'Cloud Backup Soft',  'Software',    149.00, TRUE),
    (7,  'Analytics Suite',    'Software',    899.00, TRUE),
    (8,  'Sensor Pack',        'Hardware',    119.00, TRUE),
    (9,  'Docking Station',    'Electronics',  89.00, TRUE),
    (10, 'Premium Support',    'Services',    299.00, TRUE),
    (11, 'Starter Kit',        'Hardware',     59.00, TRUE),
    (12, 'Enterprise License', 'Software',   1299.00, TRUE),
    (13, 'Accessory Bundle',   'Hardware',     39.95, TRUE),
    (14, 'Training Workshop',  'Services',    750.00, TRUE),
    (15, 'Field Router',       'Electronics', 249.00, TRUE),
    (16, 'Legacy Adapter',     'Hardware',     19.50, FALSE);

SELECT setval(pg_get_serial_sequence('products', 'id'), (SELECT MAX(id) FROM products));

-- ---------------------------------------------------------------------------
-- employees (12)
-- ---------------------------------------------------------------------------
CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    department VARCHAR(60) NOT NULL,
    region VARCHAR(50) NOT NULL,
    title VARCHAR(80) NOT NULL,
    hire_date DATE NOT NULL,
    email VARCHAR(160) NOT NULL UNIQUE
);

INSERT INTO employees (id, name, department, region, title, hire_date, email) VALUES
    (1,  'Alice Chen',     'Sales',     'North', 'Account Executive',  '2022-03-14', 'alice.chen@coia-demo.example'),
    (2,  'Bob Martinez',   'Sales',     'South', 'Account Executive',  '2021-11-02', 'bob.martinez@coia-demo.example'),
    (3,  'Carol Nguyen',   'Sales',     'East',  'Senior AE',          '2020-06-18', 'carol.nguyen@coia-demo.example'),
    (4,  'David Kim',      'Sales',     'West',  'Account Executive',  '2023-01-09', 'david.kim@coia-demo.example'),
    (5,  'Eve Patel',      'Sales',     'North', 'Account Executive',  '2022-09-26', 'eve.patel@coia-demo.example'),
    (6,  'Frank Lopez',    'Sales',     'West',  'Account Executive',  '2021-04-12', 'frank.lopez@coia-demo.example'),
    (7,  'Grace Wu',       'Sales',     'East',  'Account Executive',  '2023-05-30', 'grace.wu@coia-demo.example'),
    (8,  'Helen Okonkwo',  'Support',   'North', 'Support Specialist', '2022-07-11', 'helen.okonkwo@coia-demo.example'),
    (9,  'Ivan Petrov',    'Support',   'South', 'Support Lead',       '2019-10-03', 'ivan.petrov@coia-demo.example'),
    (10, 'Julia Rossi',    'Marketing', 'East',  'Campaign Manager',   '2021-08-17', 'julia.rossi@coia-demo.example'),
    (11, 'Ken Watanabe',   'Marketing', 'West',  'Growth Analyst',     '2023-02-21', 'ken.watanabe@coia-demo.example'),
    (12, 'Lina Berg',      'Support',   'East',  'Support Specialist', '2024-01-15', 'lina.berg@coia-demo.example');

SELECT setval(pg_get_serial_sequence('employees', 'id'), (SELECT MAX(id) FROM employees));

-- ---------------------------------------------------------------------------
-- orders (55)
-- ---------------------------------------------------------------------------
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    employee_id INTEGER REFERENCES employees(id),
    order_date DATE NOT NULL,
    status VARCHAR(30) NOT NULL,
    channel VARCHAR(50) NOT NULL,
    region VARCHAR(50) NOT NULL
);

INSERT INTO orders (id, customer_id, employee_id, order_date, status, channel, region) VALUES
    (1,  1,  1, '2024-01-12', 'completed', 'Online',  'North'),
    (2,  2,  2, '2024-01-18', 'completed', 'Retail',  'South'),
    (3,  3,  3, '2024-01-24', 'completed', 'Partner', 'East'),
    (4,  4,  4, '2024-02-02', 'completed', 'Online',  'West'),
    (5,  5,  1, '2024-02-09', 'completed', 'Direct',  'North'),
    (6,  6,  3, '2024-02-16', 'completed', 'Partner', 'East'),
    (7,  7,  7, '2024-03-05', 'completed', 'Online',  'East'),
    (8,  8,  2, '2024-03-11', 'completed', 'Online',  'South'),
    (9,  9,  6, '2024-03-19', 'completed', 'Direct',  'West'),
    (10, 10, 5, '2024-03-27', 'completed', 'Retail',  'North'),
    (11, 11, 7, '2024-04-04', 'completed', 'Online',  'East'),
    (12, 12, 4, '2024-04-12', 'completed', 'Partner', 'West'),
    (13, 13, 3, '2024-05-06', 'completed', 'Events',  'East'),
    (14, 14, 1, '2024-05-14', 'completed', 'Direct',  'North'),
    (15, 15, 6, '2024-05-22', 'completed', 'Online',  'West'),
    (16, 16, 5, '2024-06-18', 'completed', 'Online',  'North'),
    (17, 17, 1, '2024-06-25', 'completed', 'Direct',  'North'),
    (18, 18, 2, '2024-07-03', 'completed', 'Retail',  'South'),
    (19, 19, 4, '2024-07-11', 'completed', 'Partner', 'West'),
    (20, 20, 7, '2024-07-20', 'completed', 'Online',  'East'),
    (21, 21, 6, '2024-08-22', 'completed', 'Direct',  'West'),
    (22, 22, 5, '2024-08-29', 'completed', 'Online',  'North'),
    (23, 23, 2, '2024-09-05', 'completed', 'Retail',  'South'),
    (24, 24, 3, '2024-09-14', 'completed', 'Partner', 'East'),
    (25, 25, 4, '2024-09-22', 'completed', 'Online',  'West'),
    (26, 26, 7, '2024-10-03', 'completed', 'Online',  'East'),
    (27, 27, 3, '2024-10-15', 'completed', 'Direct',  'East'),
    (28, 28, 1, '2024-11-08', 'completed', 'Online',  'North'),
    (29, 29, 6, '2024-11-16', 'completed', 'Partner', 'West'),
    (30, 30, 5, '2024-11-24', 'completed', 'Retail',  'North'),
    (31, 31, 7, '2024-12-02', 'completed', 'Online',  'East'),
    (32, 32, 2, '2024-12-11', 'completed', 'Online',  'South'),
    (33, 33, 4, '2024-12-18', 'completed', 'Retail',  'West'),
    (34, 34, 6, '2025-01-14', 'completed', 'Direct',  'West'),
    (35, 35, 3, '2025-01-22', 'completed', 'Partner', 'East'),
    (36, 36, 1, '2025-02-05', 'completed', 'Online',  'North'),
    (37, 1,  1, '2025-03-08', 'completed', 'Direct',  'North'),
    (38, 9,  6, '2025-03-19', 'completed', 'Partner', 'West'),
    (39, 17, 5, '2025-04-02', 'completed', 'Online',  'North'),
    (40, 24, 3, '2025-05-12', 'completed', 'Online',  'East'),
    (41, 31, 7, '2025-05-28', 'completed', 'Direct',  'East'),
    (42, 38, 4, '2025-06-10', 'completed', 'Partner', 'West'),
    (43, 5,  1, '2025-07-08', 'completed', 'Direct',  'North'),
    (44, 14, 1, '2025-07-21', 'completed', 'Online',  'North'),
    (45, 21, 6, '2025-08-04', 'completed', 'Direct',  'West'),
    (46, 40, 4, '2025-09-18', 'completed', 'Events',  'West'),
    (47, 3,  3, '2025-10-02', 'completed', 'Partner', 'East'),
    (48, 29, 6, '2025-10-20', 'shipped',   'Online',  'West'),
    (49, 7,  7, '2025-11-06', 'shipped',   'Online',  'East'),
    (50, 12, 4, '2025-11-19', 'processing','Partner', 'West'),
    (51, 19, 2, '2026-01-08', 'completed', 'Online',  'South'),
    (52, 38, 1, '2026-01-21', 'completed', 'Direct',  'North'),
    (53, 40, 6, '2026-02-03', 'processing','Partner', 'West'),
    (54, 10, 5, '2026-02-14', 'cancelled', 'Retail',  'North'),
    (55, 27, 3, '2026-02-28', 'processing','Online',  'East');

SELECT setval(pg_get_serial_sequence('orders', 'id'), (SELECT MAX(id) FROM orders));

-- ---------------------------------------------------------------------------
-- order_items (97)
-- ---------------------------------------------------------------------------
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    line_total NUMERIC(12, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED
);

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1,  1,  12, 29.99), (1,  13, 4, 39.95),
    (2,  2,  5,  49.50), (2,  11, 2, 59.00),
    (3,  3,  8, 199.00),
    (4,  1,  20, 27.50), (4,  8,  3, 119.00),
    (5,  5,  3, 499.00),
    (6,  4,  15, 79.99), (6,  9,  2, 89.00),
    (7,  2,  7,  48.00), (7,  6,  1, 149.00),
    (8,  1,  25, 29.99),
    (9,  3,  4, 185.00), (9,  10, 2, 299.00),
    (10, 5,  2, 499.00),
    (11, 4,  18, 75.00), (11, 13, 6, 39.95),
    (12, 2,  9,  49.50),
    (13, 1,  30, 28.00), (13, 14, 1, 750.00),
    (14, 3,  6, 199.00), (14, 5,  1, 499.00),
    (15, 5,  1, 549.00),
    (16, 4,  22, 79.99), (16, 11, 3, 59.00),
    (17, 2,  11, 47.00), (17, 12, 1, 1299.00),
    (18, 1,  16, 29.99),
    (19, 3,  3, 190.00), (19, 8,  5, 119.00),
    (20, 5,  4, 499.00),
    (21, 4,  14, 72.50), (21, 9,  4, 89.00),
    (22, 2,  8,  49.50), (22, 6,  2, 149.00),
    (23, 1,  19, 27.00),
    (24, 3,  5, 199.00), (24, 7,  1, 899.00),
    (25, 5,  2, 525.00),
    (26, 4,  21, 79.99), (26, 13, 8, 39.95),
    (27, 2,  10, 46.50), (27, 10, 3, 299.00),
    (28, 1,  28, 29.99), (28, 11, 4, 59.00),
    (29, 3,  7, 188.00), (29, 15, 2, 249.00),
    (30, 5,  3, 499.00),
    (31, 4,  13, 78.00), (31, 6,  1, 149.00),
    (32, 2,  6,  49.50),
    (33, 1,  17, 26.50), (33, 13, 5, 39.95),
    (34, 3,  9, 199.00), (34, 12, 2, 1299.00),
    (35, 5,  5, 480.00),
    (36, 4,  24, 74.99), (36, 8,  2, 119.00),
    (37, 2,  12, 49.50), (37, 10, 1, 299.00),
    (38, 1,  33, 28.50), (38, 15, 3, 249.00),
    (39, 3,  2, 210.00), (39, 7,  1, 899.00),
    (40, 5,  1, 499.00), (40, 14, 2, 750.00),
    (41, 4,  16, 79.99), (41, 6,  3, 149.00),
    (42, 2,  14, 45.00), (42, 8,  6, 119.00),
    (43, 1,  23, 29.99), (43, 10, 4, 299.00),
    (44, 3,  8, 195.00), (44, 5,  2, 510.00),
    (45, 5,  6, 510.00),
    (46, 15, 5, 249.00), (46, 8,  10, 119.00), (46, 14, 1, 750.00),
    (47, 7,  2, 899.00), (47, 12, 1, 1299.00),
    (48, 4,  19, 76.00), (48, 9,  3, 89.00),
    (49, 2,  4,  49.50), (49, 11, 5, 59.00),
    (50, 1,  27, 27.99), (50, 13, 7, 39.95),
    (51, 3,  5, 199.00), (51, 6,  2, 149.00),
    (52, 5,  2, 499.00), (52, 10, 2, 299.00),
    (53, 15, 4, 249.00), (53, 8,  8, 119.00),
    (54, 1,  10, 29.99),
    (55, 7,  1, 899.00), (55, 12, 1, 1299.00), (55, 14, 1, 750.00);

SELECT setval(pg_get_serial_sequence('order_items', 'id'), (SELECT MAX(id) FROM order_items));

-- ---------------------------------------------------------------------------
-- sales_transactions (64) — denormalized fact table for Financial Analyst seed
-- ---------------------------------------------------------------------------
CREATE TABLE sales_transactions (
    id SERIAL PRIMARY KEY,
    transaction_date DATE NOT NULL,
    region VARCHAR(50) NOT NULL,
    product VARCHAR(100) NOT NULL,
    channel VARCHAR(50) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    revenue NUMERIC(12, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    customer_segment VARCHAR(50) NOT NULL,
    salesperson VARCHAR(100) NOT NULL
);

INSERT INTO sales_transactions (
    transaction_date, region, product, channel, quantity, unit_price, customer_segment, salesperson
) VALUES
    ('2024-01-05', 'North', 'Widget A', 'Online', 12, 29.99, 'SMB', 'Alice Chen'),
    ('2024-01-08', 'South', 'Widget B', 'Retail', 5, 49.50, 'Enterprise', 'Bob Martinez'),
    ('2024-01-12', 'East', 'Gadget Pro', 'Online', 8, 199.00, 'SMB', 'Carol Nguyen'),
    ('2024-01-15', 'West', 'Widget A', 'Partner', 20, 27.50, 'Enterprise', 'David Kim'),
    ('2024-01-18', 'North', 'Service Plan', 'Direct', 3, 499.00, 'Enterprise', 'Alice Chen'),
    ('2024-01-22', 'South', 'Gadget Lite', 'Online', 15, 79.99, 'Consumer', 'Eve Patel'),
    ('2024-01-25', 'East', 'Widget B', 'Retail', 7, 48.00, 'SMB', 'Carol Nguyen'),
    ('2024-01-28', 'West', 'Widget A', 'Online', 25, 29.99, 'Consumer', 'Frank Lopez'),
    ('2024-02-02', 'North', 'Gadget Pro', 'Partner', 4, 185.00, 'Enterprise', 'Alice Chen'),
    ('2024-02-05', 'South', 'Service Plan', 'Direct', 2, 499.00, 'SMB', 'Bob Martinez'),
    ('2024-02-09', 'East', 'Gadget Lite', 'Online', 18, 75.00, 'Consumer', 'Grace Wu'),
    ('2024-02-12', 'West', 'Widget B', 'Retail', 9, 49.50, 'SMB', 'David Kim'),
    ('2024-02-16', 'North', 'Widget A', 'Online', 30, 28.00, 'Consumer', 'Eve Patel'),
    ('2024-02-19', 'South', 'Gadget Pro', 'Partner', 6, 199.00, 'Enterprise', 'Frank Lopez'),
    ('2024-02-23', 'East', 'Service Plan', 'Direct', 1, 549.00, 'Enterprise', 'Carol Nguyen'),
    ('2024-02-27', 'West', 'Gadget Lite', 'Online', 22, 79.99, 'SMB', 'Grace Wu'),
    ('2024-03-01', 'North', 'Widget B', 'Retail', 11, 47.00, 'Consumer', 'Alice Chen'),
    ('2024-03-04', 'South', 'Widget A', 'Online', 16, 29.99, 'SMB', 'Bob Martinez'),
    ('2024-03-08', 'East', 'Gadget Pro', 'Partner', 3, 190.00, 'Enterprise', 'David Kim'),
    ('2024-03-11', 'West', 'Service Plan', 'Direct', 4, 499.00, 'Enterprise', 'Eve Patel'),
    ('2024-03-15', 'North', 'Gadget Lite', 'Online', 14, 72.50, 'Consumer', 'Frank Lopez'),
    ('2024-03-18', 'South', 'Widget B', 'Retail', 8, 49.50, 'SMB', 'Grace Wu'),
    ('2024-03-22', 'East', 'Widget A', 'Partner', 19, 27.00, 'Enterprise', 'Carol Nguyen'),
    ('2024-03-25', 'West', 'Gadget Pro', 'Online', 5, 199.00, 'SMB', 'Alice Chen'),
    ('2024-03-29', 'North', 'Service Plan', 'Direct', 2, 525.00, 'Enterprise', 'Bob Martinez'),
    ('2024-04-02', 'South', 'Gadget Lite', 'Online', 21, 79.99, 'Consumer', 'David Kim'),
    ('2024-04-05', 'East', 'Widget B', 'Retail', 10, 46.50, 'SMB', 'Eve Patel'),
    ('2024-04-09', 'West', 'Widget A', 'Online', 28, 29.99, 'Consumer', 'Frank Lopez'),
    ('2024-04-12', 'North', 'Gadget Pro', 'Partner', 7, 188.00, 'Enterprise', 'Grace Wu'),
    ('2024-04-16', 'South', 'Service Plan', 'Direct', 3, 499.00, 'SMB', 'Carol Nguyen'),
    ('2024-04-19', 'East', 'Gadget Lite', 'Online', 13, 78.00, 'Consumer', 'Alice Chen'),
    ('2024-04-23', 'West', 'Widget B', 'Retail', 6, 49.50, 'Enterprise', 'Bob Martinez'),
    ('2024-04-26', 'North', 'Widget A', 'Partner', 17, 26.50, 'SMB', 'David Kim'),
    ('2024-04-30', 'South', 'Gadget Pro', 'Online', 9, 199.00, 'Consumer', 'Eve Patel'),
    ('2024-05-03', 'East', 'Service Plan', 'Direct', 5, 480.00, 'Enterprise', 'Frank Lopez'),
    ('2024-05-07', 'West', 'Gadget Lite', 'Online', 24, 74.99, 'SMB', 'Grace Wu'),
    ('2024-05-10', 'North', 'Widget B', 'Retail', 12, 49.50, 'Consumer', 'Carol Nguyen'),
    ('2024-05-14', 'South', 'Widget A', 'Online', 33, 28.50, 'SMB', 'Alice Chen'),
    ('2024-05-17', 'East', 'Gadget Pro', 'Partner', 2, 210.00, 'Enterprise', 'Bob Martinez'),
    ('2024-05-21', 'West', 'Service Plan', 'Direct', 1, 499.00, 'Enterprise', 'David Kim'),
    ('2024-05-24', 'North', 'Gadget Lite', 'Online', 16, 79.99, 'Consumer', 'Eve Patel'),
    ('2024-05-28', 'South', 'Widget B', 'Retail', 14, 45.00, 'SMB', 'Frank Lopez'),
    ('2024-06-01', 'East', 'Widget A', 'Partner', 23, 29.99, 'Enterprise', 'Grace Wu'),
    ('2024-06-04', 'West', 'Gadget Pro', 'Online', 8, 195.00, 'SMB', 'Carol Nguyen'),
    ('2024-06-08', 'North', 'Service Plan', 'Direct', 6, 510.00, 'Enterprise', 'Alice Chen'),
    ('2024-06-11', 'South', 'Gadget Lite', 'Online', 19, 76.00, 'Consumer', 'Bob Martinez'),
    ('2024-06-15', 'East', 'Widget B', 'Retail', 4, 49.50, 'SMB', 'David Kim'),
    ('2024-06-18', 'West', 'Widget A', 'Online', 27, 27.99, 'Consumer', 'Eve Patel'),
    ('2024-06-22', 'North', 'Gadget Pro', 'Partner', 5, 199.00, 'Enterprise', 'Frank Lopez'),
    ('2024-06-25', 'South', 'Service Plan', 'Direct', 2, 499.00, 'SMB', 'Grace Wu'),
    -- Extended into 2025–2026 for richer time-series demos
    ('2024-09-10', 'East', 'Analytics Suite', 'Online', 1, 899.00, 'Enterprise', 'Carol Nguyen'),
    ('2024-10-05', 'West', 'Sensor Pack', 'Partner', 8, 119.00, 'SMB', 'David Kim'),
    ('2024-11-18', 'North', 'Docking Station', 'Retail', 6, 89.00, 'Consumer', 'Eve Patel'),
    ('2024-12-09', 'South', 'Enterprise License', 'Direct', 2, 1299.00, 'Enterprise', 'Bob Martinez'),
    ('2025-01-14', 'West', 'Field Router', 'Partner', 4, 249.00, 'Enterprise', 'Frank Lopez'),
    ('2025-02-20', 'North', 'Premium Support', 'Direct', 5, 299.00, 'SMB', 'Alice Chen'),
    ('2025-03-15', 'East', 'Cloud Backup Soft', 'Online', 7, 149.00, 'SMB', 'Grace Wu'),
    ('2025-05-22', 'South', 'Training Workshop', 'Events', 3, 750.00, 'Enterprise', 'Carol Nguyen'),
    ('2025-07-08', 'North', 'Widget A', 'Online', 40, 28.99, 'Consumer', 'Eve Patel'),
    ('2025-09-19', 'West', 'Field Router', 'Events', 6, 249.00, 'Enterprise', 'David Kim'),
    ('2025-11-03', 'East', 'Gadget Pro', 'Online', 11, 189.00, 'SMB', 'Grace Wu'),
    ('2026-01-12', 'South', 'Analytics Suite', 'Online', 2, 899.00, 'Enterprise', 'Bob Martinez'),
    ('2026-02-08', 'North', 'Service Plan', 'Direct', 4, 520.00, 'Enterprise', 'Alice Chen'),
    ('2026-02-25', 'West', 'Sensor Pack', 'Partner', 12, 115.00, 'SMB', 'Frank Lopez');

SELECT setval(pg_get_serial_sequence('sales_transactions', 'id'), (SELECT MAX(id) FROM sales_transactions));

-- ---------------------------------------------------------------------------
-- demo_info — human-readable catalog agents can SELECT to discover the dataset
-- ---------------------------------------------------------------------------
CREATE TABLE demo_info (
    table_name VARCHAR(64) PRIMARY KEY,
    description TEXT NOT NULL,
    example_questions TEXT NOT NULL,
    row_count_hint INTEGER
);

INSERT INTO demo_info (table_name, description, example_questions, row_count_hint) VALUES
    (
        'customers',
        'B2B/B2C accounts: name, email, country, segment (Enterprise/SMB/Consumer), signup date.',
        'How many Enterprise customers are in the USA? Which countries have the most SMB accounts?',
        40
    ),
    (
        'products',
        'Catalog of sellable items with category, unit_price, and active flag (one discontinued).',
        'What are the top 5 most expensive active products? Which categories exist?',
        16
    ),
    (
        'employees',
        'Internal staff (mostly Sales) with department, region, title, hire_date, and email.',
        'List Sales account executives by region. Who has the earliest hire_date?',
        12
    ),
    (
        'orders',
        'Order headers linking customers and optional employees; includes order_date, status, channel, region.',
        'How many orders are still processing or shipped? Orders by channel in 2025?',
        55
    ),
    (
        'order_items',
        'Line items for orders: product_id, quantity, unit_price; line_total is generated (qty * price).',
        'Which products appear most often in order lines? Total line_total by order status (join orders)?',
        97
    ),
    (
        'sales_transactions',
        'Denormalized fact table for quick analytics: date, region, product name, channel, qty, price, revenue, segment, salesperson.',
        'Revenue by region and product? Top salesperson by revenue in 2025? Trend by month?',
        64
    ),
    (
        'demo_info',
        'This catalog: table names, descriptions, and example questions for the demo dataset.',
        'SELECT * FROM demo_info; What tables are available and what can I ask about each?',
        8
    ),
    (
        'schema_version',
        'Loader marker recording which demo schema version was last applied and when.',
        'SELECT * FROM schema_version; Has the demo seed been applied?',
        1
    );

-- ---------------------------------------------------------------------------
-- schema_version — marker so loaders / agents know the seed was applied
-- ---------------------------------------------------------------------------
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT NOT NULL
);

INSERT INTO schema_version (version, notes) VALUES
    (1, 'Idempotent demo sales schema with demo_info catalog');
