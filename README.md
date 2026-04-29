# Tonn MCP Server

MCP (Model Context Protocol) server for the [RoEx Tonn API](https://tonn.roexaudio.com) — AI-powered audio mixing, mastering, and analysis.

This server exposes Tonn's audio processing capabilities as MCP tools, enabling AI assistants like Claude to mix, master, and analyse audio directly in conversation.

## Tools

| Tool | Description | Credits |
|------|-------------|---------|
| `get_account_status` | View plan, credit balance, and recent tasks | Free |
| `get_upload_url` | Get a signed URL for uploading audio files | Free |
| `analyse_mix` | Analyse a mix or master for loudness, frequency balance, stereo width, and more | Charged |
| `master_track` | Master a track with configurable loudness and style (preview or final) | Preview free, final charged |
| `get_job_status` | Check the status of a long-running processing job | Free |

## Authentication

This server uses OAuth 2.0 with the Tonn Portal as the Authorization Server. Users authenticate through their existing Tonn account — no API key pasting required.

The server implements RFC 9728 (Protected Resource Metadata) for automatic AS discovery.

## Deployment

### Cloud Run

```bash
gcloud run deploy tonn-mcp \
    --source . \
    --region europe-west1 \
    --allow-unauthenticated \
    --set-env-vars "TONN_MCP_PORTAL_URL=https://tonn-portal.roexaudio.com,TONN_MCP_API_URL=https://tonn.roexaudio.com,TONN_MCP_SERVER_URL=https://mcp.roexaudio.com"
```

### Local development

```bash
pip install -e .
TONN_MCP_PORTAL_URL=http://localhost:5000 TONN_MCP_API_URL=https://tonn.roexaudio.com TONN_MCP_SERVER_URL=http://localhost:8080 uvicorn tonn_mcp.server:app --port 8080 --reload
```

## License

MIT
