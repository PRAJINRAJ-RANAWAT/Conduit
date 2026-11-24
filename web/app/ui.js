// Tiny helpers shared by the pages (no libraries).
export const GATEWAY = process.env.NEXT_PUBLIC_GATEWAY || "http://localhost:8080";
// Public DEMO keys that are seeded into the local database. Not secrets.
export const KEYS = { alice: "key-alice", bob: "key-bob" };

export const authHeaders = (key) => ({ Authorization: `Bearer ${key}`, "Content-Type": "application/json" });

export function Badge({ children, color = "grey" }) {
  return <span className={`badge b-${color}`}>{children}</span>;
}

const STATUS_COLOR = { QUEUED: "grey", RUNNING: "blue", RETRYING: "amber", SUCCEEDED: "green", DEAD: "red" };
export const StatusBadge = ({ status }) => <Badge color={STATUS_COLOR[status] || "grey"}>{status}</Badge>;
