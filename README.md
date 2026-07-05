# Expense Splitter
A simple web application to split expenses between a group of people in a session. Built with Flask and SQLite.

## ⚠️ Security Disclaimer
This application is designed for trusted users only and does NOT implement security best practices.

This expense splitter is intended for use between friends or family members who trust each other. It lacks several security features that would be required for a production application:

- **No authentication**: Users can access any session if they know the session ID and username in the URL. There are no passwords or login verification.
- **No encryption**: Data is stored in plain text in SQLite. Communications use HTTP (not HTTPS) by default.
- **No authorization checks**: Any user who can access one session could potentially access other sessions by guessing session IDs.
- **No input validation**: Minimal protection against malicious input or SQL injection (though Flask provides some basic protections).
- **Session IDs in URLs**: Session identifiers and usernames are visible in the URL, which could be logged or cached.

Use this application only if:

- You trust everyone who has access to the server
- You're splitting expenses with people you know personally
- The financial amounts involved are small enough that security risks are acceptable
- You understand that anyone with network access to your server can potentially view or modify all expense data

For production use with untrusted users, you would need to add:

- Proper authentication (passwords, OAuth, etc.)
- HTTPS/TLS encryption
- Session management with secure tokens
- Database encryption
- Input validation and sanitization
- Rate limiting and other abuse prevention measures

This is a convenience tool for friends, not a financial security application.

## File Structure

```
expense-splitter/
├── server.py              # Flask backend
├── requirements.txt       # Python dependencies
├── Dockerfile             # Container image definition
├── docker-compose.yml     # Local container runner
├── config.json.example    # Example configuration
├── config.json            # Your actual config (DO NOT commit, gitignored)
├── .gitignore             # Git ignore file
├── database.db            # SQLite database (auto-created, gitignored)
└── templates/
    ├── home.html               # Homepage template
    └── expense_splitter.html   # Frontend HTML
```

## Installation Steps on Ubuntu Server

### 1. Set Up Python Virtual Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Install Flask
pip install -r requirements.txt
```

### 2. Configure Sessions

Edit `config.json` (NOT the .example file) to add your sessions:

```json
{
  "currencies": {
    "USD": {
      "name": "US Dollar",
      "symbol": "$",
      "rate_to_usd": 1.0
    },
    "GBP": {
      "name": "British Pound",
      "symbol": "£",
      "rate_to_usd": 1.27
    }
  },
  "sessions": {
    "your_trip_2026": {
      "description": "Summer trip shared expenses",
      "person_a": "Your Name",
      "person_b": "Friend Name",
      "users": ["yourname", "friendname"]
    },
    "apartment_expense": {
      "description": "Apartment supplies and shared bills",
      "person_a": "Alice",
      "person_b": "Bob",
      "users": ["alice", "bob"]
    }
  }
}
```

**Important:** 
- `config.json` contains your private data and is in `.gitignore`
- `config.json.example` is the template you commit to GitHub
- Never commit `config.json` to a public repository
- The homepage only shows session descriptions. Share full `/session/{session_id}/user/{username}` URLs directly with the trusted people who need them.

#### Currency Conversion

All settlement math is still done in USD. The optional `currencies` section lets the local admin define fixed conversion rates without any live exchange-rate lookup:

- `rate_to_usd` is the number of USD for 1 unit of that currency.
- `USD` is added automatically with a rate of `1.0` if it is missing.
- Each expense stores both the converted USD value and the original amount/currency so the calculation stays transparent.

If your local `config.json` does not include `currencies`, the app will only show USD.

### 3. Run the Application

```bash
# Make sure you're in the project directory with venv activated
python server.py
```

The server will start on `http://0.0.0.0:5000`

### 4. Run with Docker

The container expects your private `config.json` to be mounted at runtime and stores SQLite data in `./data`:

```bash
mkdir -p data
docker compose up --build
```

Then open `http://localhost:5000/`.

Without Compose, you can run the same image manually:

```bash
docker build -t expense-splitter .
docker run --rm -p 5000:5000 \
  -v "$(pwd)/config.json:/app/config.json:ro" \
  -v "$(pwd)/data:/data" \
  expense-splitter
```

### 5. Access the Application

- `http://localhost:5000/`


## Production Deployment

For production, you should:

### 1. Use Gunicorn instead of Flask development server

```bash
pip install gunicorn

# Run with Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 server:app
```

### 2. Set up Nginx as reverse proxy

```bash
sudo apt install nginx -y
```

Create `/etc/nginx/sites-available/expense-splitter`:

```nginx
server {
    listen 80;
    server_name your_domain.com;  # or your server IP

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/expense-splitter /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 3. Set up as a system service

Create `/etc/systemd/system/expense-splitter.service`:

```ini
[Unit]
Description=Expense Splitter
After=network.target

[Service]
User=your_username
WorkingDirectory=/home/your_username/expense-splitter
Environment="PATH=/home/your_username/expense-splitter/venv/bin"
ExecStart=/home/your_username/expense-splitter/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 server:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl start expense-splitter
sudo systemctl enable expense-splitter
```

## Firewall Configuration

If you need to access from external networks:

```bash
# Allow port 5000 (development)
sudo ufw allow 5000/tcp

# Or allow port 80 (if using Nginx)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp  # for HTTPS
```
