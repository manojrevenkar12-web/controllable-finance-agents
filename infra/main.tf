# GCP for controllable-finance-agents, in Frankfurt. The ledger (system of record) runs on Cloud Run against Cloud
# SQL for PostgreSQL over a private network, signing in with IAM, never a password. The agent worker is a Cloud Run
# job that reaches company data only through the ledger API; it has no database access at all. Events leave through
# the transactional outbox to Google Cloud Managed Service for Apache Kafka. tests/test_infra.py checks the rules.

terraform {
  required_version = ">= 1.8"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.10" }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

locals {
  labels = { app = "controllable-finance-agents", env = var.env }
  topics = toset(["cfa.documents", "cfa.proposals", "cfa.journal"])
}

# ------------------------------------------------------------------------------------------------ network

resource "google_compute_network" "vpc" {
  name                    = "cfa-${var.env}"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  name                     = "cfa-${var.env}-${var.region}"
  ip_cidr_range            = "10.20.0.0/20"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true
}

resource "google_compute_global_address" "sql_peering" {
  name          = "cfa-${var.env}-sql-peering"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "sql" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_peering.name]
}

# --------------------------------------------------------------------------------------------- identities

resource "google_service_account" "ledger" {
  account_id   = "cfa-ledger-${var.env}"
  display_name = "Ledger API (runtime database role)"
}

resource "google_service_account" "publisher" {
  account_id   = "cfa-publisher-${var.env}"
  display_name = "Outbox publisher"
}

resource "google_service_account" "worker" {
  account_id   = "cfa-worker-${var.env}"
  display_name = "Agent worker: reads and proposes through the ledger API only"
}

# ----------------------------------------------------------------------------------------------- database

resource "google_sql_database_instance" "ledger" {
  name                = "cfa-ledger-${var.env}"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.env == "prod"
  depends_on          = [google_service_networking_connection.sql]

  settings {
    tier              = var.env == "prod" ? "db-custom-2-7680" : "db-f1-micro"
    availability_type = var.env == "prod" ? "REGIONAL" : "ZONAL"
    user_labels       = local.labels

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
  }
}

resource "google_sql_database" "cfa" {
  name     = "cfa"
  instance = google_sql_database_instance.ledger.name
}

# The runtime role and the publisher sign in as their service accounts (IAM database authentication).
resource "google_sql_user" "ledger" {
  name     = trimsuffix(google_service_account.ledger.email, ".gserviceaccount.com")
  instance = google_sql_database_instance.ledger.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_sql_user" "publisher" {
  name     = trimsuffix(google_service_account.publisher.email, ".gserviceaccount.com")
  instance = google_sql_database_instance.ledger.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_project_iam_member" "ledger_sql" {
  project = var.project
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.ledger.email}"
}

resource "google_project_iam_member" "ledger_sql_login" {
  project = var.project
  role    = "roles/cloudsql.instanceUser"
  member  = "serviceAccount:${google_service_account.ledger.email}"
}

resource "google_project_iam_member" "publisher_sql" {
  project = var.project
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.publisher.email}"
}

resource "google_project_iam_member" "publisher_sql_login" {
  project = var.project
  role    = "roles/cloudsql.instanceUser"
  member  = "serviceAccount:${google_service_account.publisher.email}"
}

# ------------------------------------------------------------------------------------------------- Kafka

resource "google_managed_kafka_cluster" "events" {
  cluster_id = "cfa-${var.env}"
  location   = var.region
  labels     = local.labels

  capacity_config {
    vcpu_count   = 3
    memory_bytes = 3221225472
  }
  gcp_config {
    access_config {
      network_configs {
        subnet = google_compute_subnetwork.main.id
      }
    }
  }
}

resource "google_managed_kafka_topic" "events" {
  for_each           = local.topics
  cluster            = google_managed_kafka_cluster.events.cluster_id
  topic_id           = each.key
  location           = var.region
  partition_count    = 6
  replication_factor = 3
  configs = {
    "cleanup.policy" = "delete"
    "retention.ms"   = "604800000" # 7 days: consumers rebuild from the ledger, not from the topic
  }
}

resource "google_project_iam_member" "publisher_kafka" {
  project = var.project
  role    = "roles/managedkafka.client"
  member  = "serviceAccount:${google_service_account.publisher.email}"
}

# ------------------------------------------------------------------------------------------------ secrets

resource "google_secret_manager_secret" "jwt" {
  secret_id = "cfa-jwt-signing-key-${var.env}"
  labels    = local.labels
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
}

resource "google_secret_manager_secret" "model_key" {
  secret_id = "cfa-anthropic-api-key-${var.env}"
  labels    = local.labels
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
}

resource "google_secret_manager_secret_iam_member" "ledger_jwt" {
  secret_id = google_secret_manager_secret.jwt.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ledger.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_jwt" {
  secret_id = google_secret_manager_secret.jwt.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_model" {
  secret_id = google_secret_manager_secret.model_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

# Claude models on Vertex AI are an alternative to the API key for the worker.
resource "google_project_iam_member" "worker_vertex" {
  project = var.project
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# ------------------------------------------------------------------------------------- evaluation reports

resource "google_bigquery_dataset" "quality" {
  dataset_id  = "cfa_quality_${var.env}"
  location    = "EU"
  description = "Agent evaluation reports and per-document traces (spans, routes, cost)."
  labels      = local.labels
}

resource "google_bigquery_table" "traces" {
  dataset_id          = google_bigquery_dataset.quality.dataset_id
  table_id            = "agent_traces"
  deletion_protection = var.env == "prod"
  time_partitioning {
    type          = "DAY"
    expiration_ms = 31536000000 # one year
  }
  schema = jsonencode([
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
    { name = "document", type = "STRING", mode = "NULLABLE" },
    { name = "bucket", type = "STRING", mode = "NULLABLE" },
    { name = "confidence", type = "FLOAT64", mode = "NULLABLE" },
    { name = "spans", type = "JSON", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_dataset_iam_member" "worker_traces" {
  dataset_id = google_bigquery_dataset.quality.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.worker.email}"
}

# ---------------------------------------------------------------------------------------------- Cloud Run

resource "google_cloud_run_v2_service" "ledger" {
  name     = "cfa-ledger-${var.env}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  labels   = local.labels

  template {
    service_account = google_service_account.ledger.email
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.main.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image   = var.image
      command = ["cfa", "serve", "--host", "0.0.0.0", "--port", "8080"]
      ports { container_port = 8080 }
      env {
        name  = "CFA_ENV"
        value = "production"
      }
      env {
        name = "CFA_JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt.secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "worker" {
  name     = "cfa-agent-worker-${var.env}"
  location = var.region
  labels   = local.labels

  template {
    template {
      service_account = google_service_account.worker.email
      timeout         = "3600s"
      max_retries     = 1
      containers {
        image   = var.image
        command = ["cfa", "run", "current"]
        env {
          name  = "CFA_ENV"
          value = "production"
        }
        env {
          name = "ANTHROPIC_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.model_key.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "publisher" {
  name     = "cfa-outbox-publisher-${var.env}"
  location = var.region
  labels   = local.labels

  template {
    template {
      service_account = google_service_account.publisher.email
      containers {
        image   = var.image
        command = ["cfa", "publish"]
      }
      vpc_access {
        network_interfaces {
          network    = google_compute_network.vpc.id
          subnetwork = google_compute_subnetwork.main.id
        }
      }
    }
  }
}
