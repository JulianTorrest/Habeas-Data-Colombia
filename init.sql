CREATE TYPE request_status AS ENUM ('pending', 'accepted', 'rejected', 'failed');

CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legal_terms (
    id SERIAL PRIMARY KEY,
    version VARCHAR(50) NOT NULL UNIQUE,
    content TEXT NOT NULL,
    valid_from TIMESTAMP NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMP
);

CREATE TABLE IF NOT EXISTS habeas_requests (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    token UUID NOT NULL UNIQUE,
    status request_status DEFAULT 'pending',
    sent_at TIMESTAMP DEFAULT NOW(),
    accepted_at TIMESTAMP,
    expires_at TIMESTAMP,
    ip_address INET,
    user_agent TEXT,
    terms_version VARCHAR(50),
    campaign_id INTEGER REFERENCES campaigns(id),
    language VARCHAR(10),
    updated_at TIMESTAMP DEFAULT NOW(), -- Nuevo campo de última actualización
    UNIQUE(phone, campaign_id)
);

CREATE TABLE IF NOT EXISTS send_logs (
    id SERIAL PRIMARY KEY,
    request_id INTEGER REFERENCES habeas_requests(id),
    response_status INTEGER,
    response_body TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insertar términos legales por defecto para pruebas
INSERT INTO legal_terms (version, content) 
VALUES ('v1.0-test', 'Términos y condiciones de prueba para Habeas Data.')
ON CONFLICT (version) DO NOTHING;

-- Función para actualizar automáticamente el campo updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger que ejecuta la función anterior antes de cualquier UPDATE en habeas_requests
CREATE OR REPLACE TRIGGER update_habeas_requests_modtime
    BEFORE UPDATE ON habeas_requests
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();