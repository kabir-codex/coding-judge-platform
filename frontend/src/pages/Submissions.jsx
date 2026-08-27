import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Submissions() {
  const [subs, setSubs] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.mySubmissions()
      .then(setSubs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading submissions…</p>;

  return (
    <div>
      <h1>My Submissions</h1>
      {error && <p className="error">{error}</p>}
      <table className="problem-table">
        <thead>
          <tr><th>#</th><th>Problem</th><th>Language</th><th>Status</th><th>Tests</th><th>Runtime</th></tr>
        </thead>
        <tbody>
          {subs.map((s) => (
            <tr key={s.id}>
              <td>{s.id}</td>
              <td>{s.problem_id}</td>
              <td>{s.language}</td>
              <td className={`verdict-${s.status}`}>{s.status}</td>
              <td>{s.passed_tests}/{s.total_tests}</td>
              <td>{s.runtime_ms ? `${s.runtime_ms}ms` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

