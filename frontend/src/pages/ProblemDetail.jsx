import React, { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import Editor from "@monaco-editor/react";
import { api } from "../api.js";

const STARTER = {
  python: "import sys\n\ndef main():\n    data = sys.stdin.read().split()\n    # your code here\n\nif __name__ == '__main__':\n    main()\n",
  cpp: "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    // your code here\n    return 0;\n}\n",
  java: "import java.util.*;\n\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n        // your code here\n    }\n}\n",
};

const MONACO_LANG = { python: "python", cpp: "cpp", java: "java" };

export default function ProblemDetail() {
  const { slug } = useParams();
  const [problem, setProblem] = useState(null);
  const [language, setLanguage] = useState("python");
  const [code, setCode] = useState(STARTER.python);
  const [codeByLanguage, setCodeByLanguage] = useState({ python: STARTER.python, cpp: STARTER.cpp, java: STARTER.java });
  const [submission, setSubmission] = useState(null);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const pollRef = useRef(null);

  // Cleanup function for poll interval
  const clearPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    api.getProblem(slug).then(setProblem).catch((e) => setError(e.message));
    return () => clearPoll();
  }, [slug, clearPoll]);

  // Persist code per language
  useEffect(() => {
    if (codeByLanguage[language]) {
      setCode(codeByLanguage[language]);
    }
  }, [language, codeByLanguage]);

  function changeLanguage(lang) {
    // Save current code before switching
    setCodeByLanguage(prev => ({ ...prev, [language]: code }));
    setLanguage(lang);
    setCode(codeByLanguage[lang] || STARTER[lang]);
  }

  async function handleSubmit() {
    setError("");
    clearPoll();
    if (!localStorage.getItem("token")) {
      setError("Log in to submit code.");
      return;
    }
    setIsSubmitting(true);
    try {
      const sub = await api.submit({ problem_id: problem.id, language, source_code: code });
      setSubmission(sub);
      pollRef.current = setInterval(async () => {
        try {
          const updated = await api.getSubmission(sub.id);
          setSubmission(updated);
          if (!["QUEUED", "RUNNING"].includes(updated.status)) {
            clearPoll();
          }
        } catch (e) {
          setError(e.message);
          clearPoll();
        }
      }, 1200);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  if (error && !problem) return <p className="error">{error}</p>;
  if (!problem) return <p>Loading…</p>;

  return (
    <div className="problem-detail">
      <div className="statement-pane">
        <h1>{problem.title}</h1>
        <p className="meta">
          {problem.difficulty} · {problem.points} pts · {problem.time_limit_sec}s / {problem.memory_limit_mb}MB
        </p>
        <p className="statement">{problem.statement}</p>

        <h3>Sample tests</h3>
        {problem.sample_tests.map((tc) => (
          <div key={tc.id} className="sample-test">
            <div><strong>Input</strong><pre>{tc.input}</pre></div>
            <div><strong>Expected output</strong><pre>{tc.expected_output}</pre></div>
          </div>
        ))}
      </div>

      <div className="editor-pane">
        <div className="editor-toolbar">
          <select value={language} onChange={(e) => changeLanguage(e.target.value)}>
            <option value="python">Python 3</option>
            <option value="cpp">C++17</option>
            <option value="java">Java 21</option>
          </select>
          <button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? "Submitting…" : "Submit"}
          </button>
        </div>

        <Editor
          height="420px"
          language={MONACO_LANG[language]}
          value={code}
          onChange={(v) => setCode(v ?? "")}
          theme="vs-dark"
          options={{ fontSize: 14, minimap: { enabled: false } }}
        />

        {error && <p className="error">{error}</p>}

        {submission && (
          <div className={`verdict verdict-${submission.status}`}>
            <p><strong>{submission.status}</strong> — {submission.passed_tests}/{submission.total_tests} tests passed
              {submission.runtime_ms ? ` · ${submission.runtime_ms}ms` : ""}
              {submission.memory_kb ? ` · ${submission.memory_kb}KB` : ""}
            </p>
            {submission.stderr && <pre className="stderr">{submission.stderr}</pre>}
          </div>
        )}
      </div>
    </div>
  );
}

