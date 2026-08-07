-- Chat Sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(64) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(32) DEFAULT 'active'
);

-- Messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(64) NOT NULL REFERENCES chat_sessions(chat_id),
    sender VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agents
CREATE TABLE IF NOT EXISTS agents (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(128),
    is_online BOOLEAN DEFAULT FALSE,
    last_seen TIMESTAMP
);

-- Agent Presence in Chat
CREATE TABLE IF NOT EXISTS agent_chat_presence (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(64) NOT NULL REFERENCES chat_sessions(chat_id),
    agent_id VARCHAR(64) NOT NULL REFERENCES agents(agent_id),
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    left_at TIMESTAMP
);

-- Escalation sessions (chat-level handoff state)
CREATE TABLE IF NOT EXISTS escalation_sessions (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(64) UNIQUE NOT NULL REFERENCES chat_sessions(chat_id),
    escalated BOOLEAN DEFAULT FALSE,
    agent_id VARCHAR(64) REFERENCES agents(agent_id),
    escalation_reason VARCHAR(255),
    escalation_metadata JSONB DEFAULT '{}'::jsonb,
    escalated_at TIMESTAMP,
    agent_joined_at TIMESTAMP,
    ended_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
