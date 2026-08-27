import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Leaderboard() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.leaderboard()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading leaderboard…</p>;

  return (
    <div>
      <h1>Leaderboard</h1>
      {error && <p className="error">{error}</p>}
      <table className="problem-table">
        <thead>
          <tr><th>Rank</th><th>User</th><th>Rating</th><th>Solved</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.rank}>
              <td>{r.rank}</td>
              <td>{r.username}</td>
              <td>{r.rating}</td>
              <td>{r.solved_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

