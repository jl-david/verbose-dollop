# Looker Studio Marketing Integration

A complete pipeline that connects **Google Ads, Meta Ads (Facebook/Instagram), Google Analytics 4, LinkedIn Ads, and Twitter/X Ads** into a single BigQuery dataset and visualizes everything in Looker Studio.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Data Sources                        │
│  Google Ads · Meta Ads · GA4 · LinkedIn · Twitter/X    │
└───────────────────────────┬─────────────────────────────┘
                            │  Python connectors
                            ▼
┌─────────────────────────────────────────────────────────┐
│               Data Pipeline  (main.py)                  │
│  DataAggregator → per-platform DataFrames → Unified DF │
└───────────────────────────┬─────────────────────────────┘
                            │  BigQueryLoader
                            ▼
┌─────────────────────────────────────────────────────────┐
│                      BigQuery                           │
│  google_ads_performance   meta_ads_performance          │
│  ga4_performance          linkedin_ads_performance      │
│  twitter_ads_performance  unified_performance           │
└───────────────────────────┬─────────────────────────────┘
                            │  Community Connector (Apps Script)
                            ▼
┌─────────────────────────────────────────────────────────┐
│                   Looker Studio                         │
│  Executive Overview · Google Ads · Meta · GA4           │
│  LinkedIn · Twitter                                     │
└─────────────────────────────────────────────────────────┘
```

---

## Project Layout

```
├── connector/                   # Looker Studio Community Connector
│   ├── Code.js                  # Main Apps Script connector logic
│   ├── schema.js                # Field/schema definitions
│   └── appsscript.json          # Apps Script manifest
│
├── data_sources/                # Python API connectors
│   ├── base.py                  # Abstract BaseConnector
│   ├── google_ads.py            # Google Ads API v16
│   ├── meta_ads.py              # Meta Marketing API v19
│   ├── google_analytics.py      # GA4 Data API
│   ├── linkedin_ads.py          # LinkedIn Marketing API v2
│   └── twitter_ads.py           # Twitter Ads API v12
│
├── pipeline/                    # Orchestration & loading
│   ├── aggregator.py            # DataAggregator – runs all connectors
│   └── bigquery_loader.py       # Writes DataFrames to BigQuery
│
├── dashboard/
│   └── dashboard_config.json    # Looker Studio page/chart layout spec
│
├── config/
│   ├── config.yaml              # Static configuration
│   └── .env.example             # Environment variable template
│
├── main.py                      # CLI entry point
└── requirements.txt
```

---

## Quick Start

### 1. Clone & install dependencies

```bash
git clone <repo-url>
cd verbose-dollop
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp config/.env.example config/.env
# Edit config/.env with your API credentials
```

### 3. Set up Google Cloud

```bash
# Create a BigQuery dataset (or let the pipeline create it automatically)
gcloud auth application-default login
export GOOGLE_APPLICATION_CREDENTIALS=./config/service_account.json
```

### 4. Run the pipeline

```bash
# Fetch last 30 days from all platforms
python main.py

# Fetch specific platforms only
python main.py --platforms google_ads meta_ads

# Custom date range
python main.py --start 2024-01-01 --end 2024-01-31

# Run on a daily schedule
python main.py --schedule
```

---

## BigQuery Tables

| Table | Platform | Description |
|---|---|---|
| `google_ads_performance` | Google Ads | Campaign/ad-group metrics |
| `meta_ads_performance` | Facebook/Instagram | Ad-level insights + actions |
| `ga4_performance` | Google Analytics 4 | Session, user, conversion metrics |
| `linkedin_ads_performance` | LinkedIn | Campaign analytics |
| `twitter_ads_performance` | Twitter/X | Campaign engagement & spend |
| `unified_performance` | All | Cross-platform unified view |

**Unified table schema:**

| Column | Type | Description |
|---|---|---|
| `date` | DATE | Report date |
| `platform` | STRING | Source platform |
| `campaign_id` | STRING | Platform campaign ID |
| `campaign_name` | STRING | Campaign name |
| `impressions` | INT64 | Total impressions |
| `clicks` | INT64 | Total clicks |
| `spend` | FLOAT64 | Total spend (USD) |
| `conversions` | FLOAT64 | Total conversions |
| `ctr` | FLOAT64 | Click-through rate |
| `cpc` | FLOAT64 | Cost per click |
| `cpa` | FLOAT64 | Cost per acquisition |

---

## Looker Studio Setup

### Deploy the Community Connector

1. Go to [script.google.com](https://script.google.com) → New project
2. Copy `connector/Code.js` and `connector/schema.js` into the editor
3. Copy `connector/appsscript.json` → Project Settings → Script Properties
4. Add **Script Properties**:
   - `OAUTH_CLIENT_ID` – OAuth 2.0 client ID (BigQuery scope)
   - `OAUTH_CLIENT_SECRET` – OAuth 2.0 client secret
5. Deploy → New deployment → **Community Connector**

### Connect in Looker Studio

1. Open [Looker Studio](https://lookerstudio.google.com)
2. Create report → Add data → Community connectors → search for your connector
3. Enter:
   - **BigQuery Project ID** – your GCP project
   - **BigQuery Dataset ID** – `looker_studio_integration`
   - **Table** – choose `unified_performance` or a platform-specific table
4. Select date range and authorize

### Dashboard Pages

The `dashboard/dashboard_config.json` describes the full layout:

| Page | Contents |
|---|---|
| **Executive Overview** | Cross-platform KPI scorecards, spend trend, platform mix |
| **Google Ads** | Campaign/ad-group performance, network/device breakdown |
| **Meta Ads** | Reach, frequency, ROAS, ad-set table |
| **Google Analytics 4** | Sessions, users, geo map, source/medium |
| **LinkedIn Ads** | Leads, unique impressions, campaign table |
| **Twitter / X Ads** | Engagements, social actions, campaign table |

---

## API Credentials Guide

### Google Ads
1. [Apply for a developer token](https://developers.google.com/google-ads/api/docs/first-call/dev-token)
2. Create OAuth2 credentials in [Google Cloud Console](https://console.cloud.google.com)
3. Generate a refresh token using the OAuth playground

### Meta Ads
1. Create a [Meta App](https://developers.facebook.com/apps/)
2. Add the **Marketing API** product
3. Generate a System User token with `ads_read` permission

### Google Analytics 4
1. Enable the [Google Analytics Data API](https://console.cloud.google.com/apis)
2. Create a Service Account → download JSON key
3. Grant the service account **Viewer** role on your GA4 property

### LinkedIn Ads
1. Create an app at [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps)
2. Request the `r_ads_reporting` permission
3. Generate an access token via OAuth 2.0

### Twitter / X Ads
1. Apply for [Elevated API access](https://developer.twitter.com/en/portal/products)
2. Create an App → generate OAuth 1.0a keys and tokens
3. Request Ads API access for your account

---

## Running on a Schedule (Cloud Run Jobs)

```yaml
# cloud-run-job.yaml
apiVersion: run.googleapis.com/v1
kind: Job
metadata:
  name: marketing-pipeline
spec:
  template:
    spec:
      containers:
        - image: gcr.io/YOUR_PROJECT/marketing-pipeline:latest
          command: ["python", "main.py", "--schedule"]
          env:
            - name: GOOGLE_ADS_DEVELOPER_TOKEN
              valueFrom:
                secretKeyRef:
                  name: marketing-secrets
                  key: GOOGLE_ADS_DEVELOPER_TOKEN
            # ... add remaining secrets
```

---

## License

MIT
