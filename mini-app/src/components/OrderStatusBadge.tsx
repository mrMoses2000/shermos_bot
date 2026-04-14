export default function OrderStatusBadge({ status }: { status: string }) {
  const known = ["scheduled", "new", "confirmed", "completed", "cancelled", "rejected", "in_progress", "processing"];
  const className = known.includes(status) ? `status-${status}` : "status-default";

  return <span className={`status-badge ${className}`}>{status}</span>;
}
