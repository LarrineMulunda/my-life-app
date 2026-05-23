# GCP Deployment

## Stack
  Cloud Run  (Flask / Gunicorn)
  Cloud SQL  (PostgreSQL — swap SQLite in production)
  Secret Manager (SECRET_KEY, CRON_SECRET, DB password)
  Cloud Scheduler (daily price fetch + Friday review)

## Quick deploy

  # 1. Set project
  gcloud config set project YOUR_PROJECT_ID

  # 2. Enable services
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com

  # 3. Build and deploy
  gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/life-app
  gcloud run deploy life-app --image gcr.io/YOUR_PROJECT_ID/life-app --platform managed --region africa-south1 --allow-unauthenticated --memory 512Mi

  # 4. Daily price fetch — Mon-Fri 5 PM EAT (14:00 UTC)
  gcloud scheduler jobs create http fetch-prices --schedule="0 14 * * 1-5" --uri="SERVICE_URL/api/stocks/fetch-prices" --message-body='{}' --http-method=POST

  # 5. Friday review — 6 PM EAT (15:00 UTC)
  gcloud scheduler jobs create http friday-review --schedule="0 15 * * 5" --uri="SERVICE_URL/api/portfolio/review" --message-body='{}' --http-method=POST
