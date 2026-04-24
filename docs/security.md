# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

# Security Best Practices Guide

## External Mirrors / Public Dashboard (v0.14.0+)

The optional public dashboard mirror is **outbound-only** by design — the home backend never opens an inbound port for the receiver. Push deliveries are signed and use a strict public projection so the public replica cannot leak operator-private state.

- **Transport**: HTTPS POST from home backend → receiver `ingest.php`. The home backend remains on the LAN; the receiver lives on shared hosting.
- **Authentication**: `Authorization: Bearer <plaintext-token>` plus an HMAC-SHA256 signature over `timestamp + "\n" + nonce + "\n" + raw_body`. Tokens are stored bcrypt-hashed at rest in the home backend; plaintext is shown only once at create / rotate.
- **Replay protection**: ±300 s clock skew window enforced by the receiver, plus a per-mirror nonce cache (`mirror_seen_nonces`) — replays return HTTP 409.
- **Public projection of `settings` snapshot**: the bundler strips `auth`, `aprs`, `lora_aprs`, `asr`, `device_config`, and `audio_config` before publishing. Operator credentials, private hardware identifiers, ASR model paths, and device configuration are **never** part of the public payload.
- **Raw event cap**: each push carries at most `RAW_EVENTS_CAP = 1500` events to keep payloads under typical shared-hosting `post_max_size`.
- **Surface limits**: the receiver exposes only read-only endpoints (`api/version`, `api/scan/status`, `api/settings`, `api/map/*`, `api/analytics/academic`, `api/events`). It has **no** WebSocket, **no** admin surface, **no** SDR control, and **no** auth/login endpoints.
- **Failure isolation**: a mirror that fails 5 consecutive pushes is auto-disabled until an admin re-enables it.

For the full protocol specification see [`docs/external_mirrors.md`](external_mirrors.md).

## Authentication

### Password Security

**CRITICAL**: Never use plaintext passwords in production!

1. **Generate a bcrypt hash** for your password:
   ```bash
   cd scripts
   python hash_password.py
   ```

2. **Update your `.env` file** with the hash:
   ```
   BASIC_AUTH_USER=admin
   BASIC_AUTH_PASS=$2b$12$your_generated_hash_here
   ```

3. **Enable authentication**:
   ```
   AUTH_REQUIRED=1
   ```

### Default Credentials

The default credentials (`admin`/`changeme`) are for **development only**.

**Before deployment:**
- [ ] Change default username
- [ ] Generate strong password hash
- [ ] Enable authentication (`AUTH_REQUIRED=1`)

## Rate Limiting

The application includes built-in rate limiting to prevent abuse:

- **Scan operations**: 10 requests per minute
- **Events API**: 30 requests per minute
- **General endpoints**: Default FastAPI limits

Rate limits are per IP address.

## CORS Configuration

Configure CORS (Cross-Origin Resource Sharing) based on your deployment:

### Development
```env
CORS_ENABLED=1
CORS_ORIGINS=*
```

### Production
```env
CORS_ENABLED=1
CORS_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
```

**Never use `*` in production** - specify exact origins!

## Security Headers

The application automatically adds security headers to all responses:

- `X-Content-Type-Options: nosniff` - Prevents MIME type sniffing
- `X-Frame-Options: DENY` - Prevents clickjacking
- `X-XSS-Protection: 1; mode=block` - XSS protection
- `Referrer-Policy: strict-origin-when-cross-origin` - Referrer control

## HTTPS/TLS

**REQUIRED for production deployments!**

### Using Reverse Proxy (Recommended)

Use nginx or Apache as reverse proxy with Let's Encrypt:

```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;
    
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # WebSocket support
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

### Direct HTTPS (Alternative)

Run uvicorn with SSL:
```bash
uvicorn app.main:app \
    --app-dir backend \
    --host 0.0.0.0 \
    --port 8443 \
    --ssl-keyfile /path/to/key.pem \
    --ssl-certfile /path/to/cert.pem
```

## Firewall Configuration

### Minimum Required Ports

- **8000**: HTTP (development) or HTTPS (production)
- **22**: SSH (restrict to known IPs)

### Recommended iptables Rules

```bash
# Allow established connections
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow loopback
iptables -A INPUT -i lo -j ACCEPT

# Allow SSH (change port if using non-standard)
iptables -A INPUT -p tcp --dport 22 -j ACCEPT

# Allow HTTP/HTTPS
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# Drop everything else
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT
```

## Dependency Security

### Regular Updates

Keep dependencies up to date:

```bash
# Update pip
python -m pip install --upgrade pip

# Update all packages
pip install --upgrade -r backend/requirements.txt

# Check for vulnerabilities
pip-audit
```

### Audit Dependencies

Install and run pip-audit regularly:

```bash
pip install pip-audit
pip-audit
```

## Environment Variables

### Sensitive Data

**NEVER commit `.env` files to version control!**

- Use `.env.example` as template
- Store actual `.env` locally or in secure secrets management
- In production, use environment variables or secrets manager

### Secret Management

For production deployments, consider:

- **Docker Secrets** (if using Docker Swarm)
- **Kubernetes Secrets** (if using Kubernetes)
- **HashiCorp Vault** (enterprise)
- **AWS Secrets Manager** (if using AWS)
- **systemd environment files** (for systemd services)

## File Permissions

### Linux/Unix

```bash
# Application files
chmod 755 backend/app/
chmod 644 backend/app/*.py

# Configuration files (sensitive)
chmod 600 .env
chmod 600 config/*.yaml

# Data directory
chmod 700 data/
chmod 600 data/events.sqlite

# Scripts
chmod 755 scripts/*.sh
chmod 755 scripts/*.py
```

### Ownership

Run application as non-root user:

```bash
# Create dedicated user
sudo useradd -r -s /bin/false 4ham

# Set ownership
sudo chown -R 4ham:4ham /path/to/4ham-spectrum-analysis

# Run as this user
sudo -u 4ham python -m uvicorn app.main:app --app-dir backend
```

## Logging and Monitoring

### Security Events to Monitor

- Failed authentication attempts
- Rate limit violations
- Unusual API access patterns
- Database errors
- System resource exhaustion

### Log Management

```env
LOG_LEVEL=WARNING  # Don't log sensitive data in INFO/DEBUG
LOG_FILE=/var/log/4ham/app.log
```

Rotate logs regularly:

```bash
# /etc/logrotate.d/4ham
/var/log/4ham/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 4ham 4ham
    sharedscripts
}
```

## Backup and Recovery

### Database Backups

```bash
# Automated backup script
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/var/backups/4ham"
mkdir -p "$BACKUP_DIR"
sqlite3 data/events.sqlite ".backup '$BACKUP_DIR/events_$DATE.sqlite'"
# Keep last 30 days
find "$BACKUP_DIR" -name "events_*.sqlite" -mtime +30 -delete
```

### Configuration Backups

Backup `.env` and `config/` directory separately and securely.

## Security Checklist

### Before Deployment

- [ ] Change default credentials
- [ ] Generate bcrypt password hash
- [ ] Enable authentication (`AUTH_REQUIRED=1`)
- [ ] Configure CORS with specific origins
- [ ] Set up HTTPS with valid certificate
- [ ] Configure firewall rules
- [ ] Set proper file permissions
- [ ] Run as non-root user
- [ ] Enable log rotation
- [ ] Set up automated backups
- [ ] Review all environment variables
- [ ] Audit dependencies with pip-audit
- [ ] Test authentication and rate limiting
- [ ] Remove or disable debug endpoints

### Regular Maintenance

- [ ] Update dependencies monthly
- [ ] Run pip-audit weekly
- [ ] Review logs for anomalies
- [ ] Test backup restoration procedures
- [ ] Renew SSL certificates (if not using Let's Encrypt auto-renewal)
- [ ] Review and update firewall rules
- [ ] Audit user access and permissions

## Incident Response

### In Case of Security Breach

1. **Isolate**: Disconnect system from network
2. **Assess**: Determine scope of breach
3. **Contain**: Stop the attack vector
4. **Eradicate**: Remove malicious code/access
5. **Recover**: Restore from clean backups
6. **Review**: Update security measures

### Emergency Contacts

Maintain a list of:
- System administrators
- Security team contacts
- Hosting provider support
- Incident response service (if applicable)

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Python Security Best Practices](https://python.readthedocs.io/en/latest/library/security_warnings.html)
- [Let's Encrypt](https://letsencrypt.org/)
- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)

---

**Remember**: Security is an ongoing process, not a one-time setup!
