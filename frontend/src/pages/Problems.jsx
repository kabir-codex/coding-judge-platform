import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

const DIFFICULTY_CLASS = { EASY: "diff-easy", MEDIUM: "diff-medium", HARD: "diff-hard" };

export default function Problems() {
  const [problems, setProblems] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.listProblems()
      .then(setProblems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading problems…</p>;

  return (
    <div>
      <h1>Problems</h1>
      {error && <p className="error">{error}</p>}
      <table className="problem-table">
        <thead>
          <tr><th>Title</th><th>Difficulty</th><th>Points</th></tr>
        </thead>
        <tbody>
          {problems.map((p) => (
            <tr key={p.id}>
              <td><Link to={`/problems/${p.slug}`}>{p.title}</Link></td>
              <td><span className={DIFFICULTY_CLASS[p.difficulty]}>{p.difficulty}</span></td>
              <td>{p.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

