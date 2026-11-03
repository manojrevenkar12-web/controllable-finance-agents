output "ledger_url" { value = google_cloud_run_v2_service.ledger.uri }
output "database_instance" { value = google_sql_database_instance.ledger.connection_name }
output "kafka_cluster" { value = google_managed_kafka_cluster.events.cluster_id }
