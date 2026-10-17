"use client";

import React, { useState, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  AlertCircle,
  Info,
  Upload,
  FileText,
  FileUp,
  RotateCcw,
  CheckCircle2,
  Cpu,
  Clock,
  Sparkles,
  Zap,
  ExternalLink,
  ChevronRight,
  Filter,
  Check,
  Search,
  Layers,
  ArrowRight,
} from "lucide-react";
import {
  DocumentResponse,
  FindingModel,
  AnalysisResponse,
  SeverityLevel,
} from "@/types";
import TextViewer from "@/components/TextViewer";

// Dynamically import PdfViewer to disable server-side rendering (canvas/pdf.js requires browser window)
const PdfViewer = dynamic(() => import("@/components/PdfViewer"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-col items-center justify-center h-full min-h-[450px] bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-400 gap-3">
      <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-xs font-medium">Initializing PDF Rendering Engine...</p>
    </div>
  ),
});

const SAMPLE_TOS_TEXT = `CloudScale Terms of Service

1. Acceptance of Terms
By accessing or using the CloudScale Services, you agree to be bound by these Terms of Service. If you do not agree to these terms, do not use the Services.

2. Service Description
CloudScale provides managed cloud computing infrastructure, database hosting, and related developer tools as described on our website.

3. Modification of Terms
CloudScale reserves the right to modify, amend, or replace these Terms at any time at its sole discretion without prior notice to you. Your continued use of the Services following any changes constitutes acceptance of the modified Terms.

4. Limitation of Liability
To the maximum extent permitted by applicable law, in no event shall CloudScale, its affiliates, or directors be liable for any indirect, incidental, punitive, or consequential damages. In no event shall CloudScale's total aggregate liability exceed twenty-five dollars ($25.00).

5. Mandatory Binding Arbitration and Class Action Waiver
Any dispute, controversy, or claim arising out of or relating to this agreement shall be settled exclusively by confidential binding arbitration in Wilmington, Delaware. You hereby waive any right to participate as a plaintiff or class member in any class action or representative proceeding.

6. Termination of Services
CloudScale may suspend or terminate your access to the Services immediately, with or without cause, and without prior notice or liability. Upon termination, your right to use the Services will cease immediately.`;

const CATEGORY_LABELS: Record<string, string> = {
  arbitration: "Mandatory Arbitration",
  unilateral_change: "Unilateral Modification",
  limitation_of_liability: "Limitation of Liability",
  unilateral_termination: "Unilateral Termination",
  content_removal: "Content Removal",
  jurisdiction: "Forum Selection",
  choice_of_law: "Choice of Law",
  contract_by_using: "Contract by Mere Use",
};

export default function HomePage() {
  const [tab, setTab] = useState<"upload" | "paste">("upload");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [pastedText, setPastedText] = useState<string>("");
  const [isDragOver, setIsDragOver] = useState(false);

  // Analysis settings
  const [isDryRun, setIsDryRun] = useState(true);

  // State machine: idle -> uploading -> analyzing -> done | error
  const [status, setStatus] = useState<
    "idle" | "uploading" | "analyzing" | "done" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [progressMsg, setProgressMsg] = useState<string>("");
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);

  // Data
  const [document, setDocument] = useState<DocumentResponse | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResponse | null>(
    null
  );
  const [filterSeverity, setFilterSeverity] = useState<string>("all");
  const [backendAlive, setBackendAlive] = useState<boolean | null>(null);

  // Active / Selected Citation state (one code path for click-to-scroll)
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [selectedClauseId, setSelectedClauseId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Check backend health on mount
  useEffect(() => {
    fetch("/api/health")
      .then((res) => {
        if (res.ok) setBackendAlive(true);
        else setBackendAlive(false);
      })
      .catch(() => setBackendAlive(false));
  }, []);

  // Timer while analyzing
  useEffect(() => {
    let interval: NodeJS.Timeout | null = null;
    if (status === "analyzing" || status === "uploading") {
      interval = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } else {
      setElapsedSeconds(0);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [status]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (ext === "pdf" || ext === "txt") {
        setSelectedFile(file);
      } else {
        alert("Please upload a PDF (.pdf) or Text (.txt) file.");
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0]);
    }
  };

  // Unified scroll-to-clause for both PDF and Text renderers
  const handleSelectFinding = (finding: FindingModel) => {
    setSelectedFindingId(finding.id);
    setSelectedClauseId(finding.clause_id);

    // Scroll to the target clause element in whichever viewer is rendered
    setTimeout(() => {
      const el = window.document.getElementById(`clause-${finding.clause_id}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 70);
  };

  const handleClauseClick = (clauseId: string) => {
    setSelectedClauseId(clauseId);
    const relatedFinding = analysisResult?.findings.find(
      (f) => f.clause_id === clauseId
    );
    if (relatedFinding) {
      setSelectedFindingId(relatedFinding.id);
    }
  };

  // Main flow: Ingest -> Poll Document Status -> Run Analysis -> Render Findings
  const handleAnalyze = async () => {
    setErrorMessage(null);
    setStatus("uploading");
    setProgressMsg("Ingesting document and segmenting clauses...");

    try {
      let createdDoc: DocumentResponse;

      if (tab === "upload") {
        if (!selectedFile) {
          throw new Error("Please select a file to analyze.");
        }
        const formData = new FormData();
        formData.append("file", selectedFile);
        const res = await fetch("/api/documents", {
          method: "POST",
          body: formData,
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(
            errData.detail || `Upload failed with HTTP ${res.status}`
          );
        }
        createdDoc = await res.json();
      } else {
        if (!pastedText.trim()) {
          throw new Error("Please enter contract text to analyze.");
        }
        const res = await fetch("/api/documents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: pastedText,
            filename: "pasted_terms.txt",
          }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(
            errData.detail || `Text upload failed with HTTP ${res.status}`
          );
        }
        createdDoc = await res.json();
      }

      setDocument(createdDoc);
      setStatus("analyzing");
      setProgressMsg(
        isDryRun
          ? "Running deterministic UNFAIR-ToS rubric verification ($0 offline mode)..."
          : "Analyzing clauses with local Ollama LLM (qwen2.5:7b-instruct)..."
      );

      // Start polling document status in background
      const docId = createdDoc.id;
      const pollInterval = setInterval(async () => {
        try {
          const pollRes = await fetch(`/api/documents/${docId}`);
          if (pollRes.ok) {
            const polledData: DocumentResponse = await pollRes.json();
            setDocument(polledData);
            if (polledData.status === "analyzed") {
              setProgressMsg("Analysis complete. Loading verified findings...");
            }
          }
        } catch {
          // ignore transient poll error
        }
      }, 1000);

      // Trigger analysis endpoint
      const analyzeUrl = `/api/documents/${docId}/analyze?lens=tos&dry_run=${isDryRun}`;
      const analyzeRes = await fetch(analyzeUrl, {
        method: "POST",
      });

      clearInterval(pollInterval);

      if (!analyzeRes.ok) {
        const errJson = await analyzeRes.json().catch(() => ({}));
        throw new Error(
          errJson.detail || `Analysis failed with HTTP ${analyzeRes.status}`
        );
      }

      const result: AnalysisResponse = await analyzeRes.json();
      setAnalysisResult(result);

      // Re-fetch document one final time
      const finalDocRes = await fetch(`/api/documents/${docId}`).catch(
        () => null
      );
      if (finalDocRes && finalDocRes.ok) {
        const finalDoc = await finalDocRes.json();
        setDocument(finalDoc);
      }

      setStatus("done");

      // Auto-select first finding if available
      if (result.findings.length > 0) {
        handleSelectFinding(result.findings[0]);
      }
    } catch (err: unknown) {
      setStatus("error");
      const message =
        err instanceof Error ? err.message : "An unexpected error occurred.";
      setErrorMessage(message);
    }
  };

  const handleReset = () => {
    setStatus("idle");
    setSelectedFile(null);
    setPastedText("");
    setDocument(null);
    setAnalysisResult(null);
    setSelectedFindingId(null);
    setSelectedClauseId(null);
    setErrorMessage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const findings = analysisResult?.findings || [];
  const filteredFindings = findings.filter((f) => {
    if (filterSeverity === "all") return true;
    return f.severity === filterSeverity;
  });

  const redCount = findings.filter((f) => f.severity === "red").length;
  const yellowCount = findings.filter((f) => f.severity === "yellow").length;
  const infoCount = findings.filter((f) => f.severity === "info").length;

  // Grounding statistics derived directly from findings payload
  const verifiedCount = findings.filter(
    (f) => f.verification_status === "verified"
  ).length;
  const fuzzyCount = findings.filter(
    (f) => f.verification_status === "verified_fuzzy"
  ).length;
  const reanchoredCount = findings.filter(
    (f) => f.verification_status === "reanchored"
  ).length;

  const selectedFinding =
    findings.find((f) => f.id === selectedFindingId) || null;

  return (
    <div className="flex flex-col min-h-screen bg-slate-950 text-slate-100">
      {/* Top Header */}
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-violet-600 to-cyan-400 p-[1px] shadow-lg shadow-indigo-500/20">
              <div className="h-full w-full bg-slate-950 rounded-xl flex items-center justify-center">
                <ShieldCheck className="h-5 w-5 text-indigo-400" />
              </div>
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                  What Did I Agree To?
                </span>
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                  Phase 6b
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Local-first legal Terms of Service analyzer with verified citations
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-3 text-xs">
            {backendAlive === true && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Backend Connected
              </span>
            )}
            {backendAlive === false && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20 font-medium">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
                Backend Offline (port 8000)
              </span>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main
        className={`flex-1 w-full mx-auto px-4 sm:px-6 py-6 transition-all ${
          status === "done" ? "max-w-[1700px]" : "max-w-5xl"
        }`}
      >
        {/* Hero Banner (Only shown in idle/uploading) */}
        {status === "idle" && (
          <div className="text-center mb-8 sm:mb-10 pt-2 sm:pt-4">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800/80 border border-slate-700/60 text-xs text-slate-300 mb-4 shadow-inner">
              <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
              <span>Deterministic Citation Verification — No Fabricated Claims</span>
            </div>
            <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white mb-3">
              Know what you sign before you click{" "}
              <span className="bg-gradient-to-r from-indigo-400 via-violet-400 to-cyan-400 bg-clip-text text-transparent">
                "I Agree"
              </span>
            </h1>
            <p className="text-slate-400 max-w-2xl mx-auto text-sm sm:text-base leading-relaxed">
              Upload any contract or Terms of Service PDF. Our local AI pipeline segments clauses,
              detects unfair provisions like arbitration traps and unilateral waivers, and
              verifies every quote character-for-character against the original text.
            </p>
          </div>
        )}

        {/* INPUT STATE (Idle or Error) */}
        {(status === "idle" || status === "error") && (
          <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur-sm">
            {/* Error Alert */}
            {errorMessage && (
              <div className="mb-6 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold text-rose-200">Analysis Error</p>
                  <p className="mt-0.5 text-rose-300/90">{errorMessage}</p>
                </div>
              </div>
            )}

            {/* Tab Navigation */}
            <div className="flex border-b border-slate-800 mb-6 gap-2">
              <button
                type="button"
                onClick={() => setTab("upload")}
                className={`flex items-center gap-2 pb-3 px-4 text-sm font-medium border-b-2 transition-all ${
                  tab === "upload"
                    ? "border-indigo-500 text-indigo-400"
                    : "border-transparent text-slate-400 hover:text-slate-200"
                }`}
              >
                <Upload className="h-4 w-4" />
                Upload PDF / TXT
              </button>
              <button
                type="button"
                onClick={() => setTab("paste")}
                className={`flex items-center gap-2 pb-3 px-4 text-sm font-medium border-b-2 transition-all ${
                  tab === "paste"
                    ? "border-indigo-500 text-indigo-400"
                    : "border-transparent text-slate-400 hover:text-slate-200"
                }`}
              >
                <FileText className="h-4 w-4" />
                Paste Text
              </button>
            </div>

            {/* TAB 1: FILE DROPZONE */}
            {tab === "upload" && (
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragOver(true);
                }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-xl p-8 sm:p-12 text-center cursor-pointer transition-all ${
                  isDragOver
                    ? "border-indigo-500 bg-indigo-500/10 scale-[0.99]"
                    : "border-slate-700/80 hover:border-slate-600 bg-slate-950/40 hover:bg-slate-900/40"
                }`}
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  accept=".pdf,.txt"
                  className="hidden"
                />

                <div className="mx-auto w-14 h-14 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 mb-4 shadow-inner">
                  <FileUp className="h-7 w-7" />
                </div>

                {selectedFile ? (
                  <div className="space-y-1">
                    <p className="font-semibold text-white text-base">
                      {selectedFile.name}
                    </p>
                    <p className="text-xs text-slate-400">
                      {(selectedFile.size / 1024).toFixed(1)} KB • Click to choose a different file
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <p className="text-sm font-semibold text-white">
                      Drop contract PDF or text file here, or{" "}
                      <span className="text-indigo-400 underline underline-offset-2">
                        browse files
                      </span>
                    </p>
                    <p className="text-xs text-slate-400">
                      Supports PDF (.pdf) and plain text (.txt). Runs 100% locally.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: PASTED TEXT */}
            {tab === "paste" && (
              <div className="space-y-3">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>Paste Terms of Service or Privacy Policy text</span>
                  <button
                    type="button"
                    onClick={() => setPastedText(SAMPLE_TOS_TEXT)}
                    className="text-indigo-400 hover:text-indigo-300 font-medium cursor-pointer transition-colors"
                  >
                    Load Sample Document
                  </button>
                </div>
                <textarea
                  value={pastedText}
                  onChange={(e) => setPastedText(e.target.value)}
                  placeholder="Paste contract terms or clause text here..."
                  rows={9}
                  className="w-full bg-slate-950/60 border border-slate-800 rounded-xl p-4 text-xs sm:text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent font-mono leading-relaxed"
                />
              </div>
            )}

            {/* Engine Options & Submit Action */}
            <div className="mt-6 pt-6 border-t border-slate-800 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <label className="text-xs font-medium text-slate-400 flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isDryRun}
                    onChange={(e) => setIsDryRun(e.target.checked)}
                    className="rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-indigo-500 h-4 w-4"
                  />
                  <span>
                    Fast Dry-Run Mode{" "}
                    <span className="text-slate-500">($0 / ~30ms offline)</span>
                  </span>
                </label>
              </div>

              <button
                type="button"
                onClick={handleAnalyze}
                disabled={tab === "upload" ? !selectedFile : !pastedText.trim()}
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold shadow-lg shadow-indigo-600/30 transition-all cursor-pointer"
              >
                <Zap className="h-4 w-4" />
                Analyze Terms of Service
              </button>
            </div>
          </div>
        )}

        {/* ANALYZING STATE (Active Polling) */}
        {(status === "uploading" || status === "analyzing") && (
          <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-10 sm:p-14 text-center shadow-2xl backdrop-blur-sm max-w-xl mx-auto my-8">
            <div className="relative mx-auto w-20 h-20 mb-6">
              <div className="absolute inset-0 rounded-full border-4 border-indigo-500/20 border-t-indigo-500 animate-spin" />
              <div className="absolute inset-2 rounded-full border-4 border-violet-500/20 border-b-violet-500 animate-spin [animation-direction:reverse]" />
              <div className="h-full w-full flex items-center justify-center">
                <ShieldAlert className="h-8 w-8 text-indigo-400" />
              </div>
            </div>

            <h2 className="text-xl font-bold text-white mb-2">
              Analyzing Legal Document…
            </h2>
            <p className="text-sm text-slate-400 mb-6">{progressMsg}</p>

            <div className="inline-flex items-center gap-3 px-4 py-2 rounded-full bg-slate-950/80 border border-slate-800 text-xs text-slate-400">
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-indigo-400" />
                Elapsed: <strong className="text-white">{elapsedSeconds}s</strong>
              </span>
              <span className="text-slate-700">•</span>
              <span>
                Status:{" "}
                <strong className="text-indigo-300 uppercase">
                  {document?.status || "uploading"}
                </strong>
              </span>
              {document && (
                <>
                  <span className="text-slate-700">•</span>
                  <span>
                    Clauses:{" "}
                    <strong className="text-white">
                      {document.clauses?.length ?? 0}
                    </strong>
                  </span>
                </>
              )}
            </div>

            <p className="text-xs text-slate-400 mt-6 max-w-sm mx-auto">
              Extracting spans, segmenting boundaries, and validating quotes character-for-character against source text.
            </p>
          </div>
        )}

        {/* COMPLETED STATE: Split-Screen View (Document Viewer + Findings List) */}
        {status === "done" && analysisResult && document && (
          <div className="space-y-6">
            {/* Top Document Header & Grounding Telemetry Banner */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 sm:p-6 backdrop-blur-sm shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-xl font-bold text-white">
                      Legal Risk Analysis Report
                    </h2>
                    <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                      Analysis Complete
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1">
                    Document:{" "}
                    <span className="text-slate-200 font-medium">
                      {document.filename || "Uploaded Contract"}
                    </span>{" "}
                    • {document.clauses.length} clauses segmented
                  </p>
                </div>

                <button
                  type="button"
                  onClick={handleReset}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 transition-colors w-fit cursor-pointer"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Analyze Another Document
                </button>
              </div>

              {/* Grounding Statistics Grid (derived from findings payload) */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-4">
                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Grounding Rate
                  </span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-xl font-extrabold text-emerald-400">
                      {(analysisResult.run.grounding_rate * 100).toFixed(0)}%
                    </span>
                    <span className="text-[10px] text-slate-400">overall</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Exact Verified
                  </span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-xl font-extrabold text-emerald-300">
                      {verifiedCount}
                    </span>
                    <span className="text-[10px] text-slate-400">findings</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Fuzzy Verified
                  </span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-xl font-extrabold text-amber-300">
                      {fuzzyCount}
                    </span>
                    <span className="text-[10px] text-slate-400">near-miss</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Reanchored
                  </span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-xl font-extrabold text-sky-300">
                      {reanchoredCount}
                    </span>
                    <span className="text-[10px] text-slate-400">relocated</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80 col-span-2 sm:col-span-1">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Latency & Cost
                  </span>
                  <div className="mt-1">
                    <span className="text-sm font-bold text-white block">
                      {analysisResult.run.latency_ms > 1000
                        ? `${(analysisResult.run.latency_ms / 1000).toFixed(1)}s`
                        : `${analysisResult.run.latency_ms.toFixed(0)}ms`}
                    </span>
                    <span className="text-[10px] text-slate-400">
                      ${analysisResult.run.cost_usd.toFixed(4)}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* SPLIT SCREEN VIEW: Document Viewer Beside Findings List */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* LEFT PANE: Document Viewer (PDF or Text) */}
              <div className="lg:col-span-7 h-[780px] flex flex-col">
                {document.source_type === "pdf" ? (
                  <PdfViewer
                    file={selectedFile}
                    clauses={document.clauses}
                    selectedClauseId={selectedClauseId}
                    onSelectClause={handleClauseClick}
                  />
                ) : (
                  <TextViewer
                    clauses={document.clauses}
                    selectedClauseId={selectedClauseId}
                    onSelectClause={handleClauseClick}
                    selectedFindingQuote={selectedFinding?.quote}
                  />
                )}
              </div>

              {/* RIGHT PANE: Findings List */}
              <div className="lg:col-span-5 h-[780px] flex flex-col bg-slate-900/40 border border-slate-800/80 rounded-2xl p-4 backdrop-blur-sm shadow-xl">
                {/* Findings Header & Filter */}
                <div className="pb-3 border-b border-slate-800 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                      <ShieldAlert className="w-4 h-4 text-amber-400" />
                      Detected Unfair Terms ({findings.length})
                    </span>
                    <span className="text-[11px] text-slate-400">
                      Click a finding to highlight
                    </span>
                  </div>

                  {/* Filter Pills */}
                  <div className="flex items-center gap-1 bg-slate-950/80 border border-slate-800/80 p-1 rounded-xl text-xs">
                    <button
                      type="button"
                      onClick={() => setFilterSeverity("all")}
                      className={`flex-1 py-1 px-2 rounded-lg font-medium text-center transition-all ${
                        filterSeverity === "all"
                          ? "bg-slate-800 text-white"
                          : "text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      All ({findings.length})
                    </button>
                    <button
                      type="button"
                      onClick={() => setFilterSeverity("red")}
                      className={`flex-1 py-1 px-2 rounded-lg font-medium text-center transition-all flex items-center justify-center gap-1 ${
                        filterSeverity === "red"
                          ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                          : "text-slate-400 hover:text-rose-300"
                      }`}
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
                      Red ({redCount})
                    </button>
                    <button
                      type="button"
                      onClick={() => setFilterSeverity("yellow")}
                      className={`flex-1 py-1 px-2 rounded-lg font-medium text-center transition-all flex items-center justify-center gap-1 ${
                        filterSeverity === "yellow"
                          ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                          : "text-slate-400 hover:text-amber-300"
                      }`}
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                      Yellow ({yellowCount})
                    </button>
                  </div>
                </div>

                {/* Findings Cards List */}
                <div className="flex-1 overflow-y-auto space-y-3 pt-3 pr-1 custom-scrollbar">
                  {filteredFindings.length === 0 ? (
                    <div className="h-64 flex flex-col items-center justify-center text-center p-6 text-slate-400 text-xs">
                      <CheckCircle2 className="w-8 h-8 text-emerald-400 mb-2" />
                      <p>No findings for the selected filter.</p>
                    </div>
                  ) : (
                    filteredFindings.map((finding) => {
                      const isSelected = selectedFindingId === finding.id;

                      return (
                        <div
                          key={finding.id}
                          onClick={() => handleSelectFinding(finding)}
                          className={`p-4 rounded-xl border transition-all duration-200 cursor-pointer text-left ${
                            isSelected
                              ? "bg-amber-950/20 border-amber-500 ring-2 ring-amber-400/50 shadow-xl shadow-amber-500/10 scale-[1.01]"
                              : "bg-slate-900/60 border-slate-800/80 hover:border-slate-700 hover:bg-slate-900/90"
                          }`}
                        >
                          {/* Top Badges Row */}
                          <div className="flex items-center justify-between gap-2 mb-2">
                            <div className="flex items-center gap-2">
                              {/* Severity Badge */}
                              <span
                                className={`text-[10px] font-bold px-2 py-0.5 rounded-md uppercase tracking-wider flex items-center gap-1 ${
                                  finding.severity === "red"
                                    ? "bg-rose-500/15 text-rose-300 border border-rose-500/30"
                                    : finding.severity === "yellow"
                                    ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                                    : "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                                }`}
                              >
                                {finding.severity === "red" && (
                                  <AlertCircle className="h-3 w-3" />
                                )}
                                {finding.severity === "yellow" && (
                                  <AlertTriangle className="h-3 w-3" />
                                )}
                                {finding.severity === "info" && (
                                  <Info className="h-3 w-3" />
                                )}
                                {finding.severity === "red"
                                  ? "High Risk"
                                  : finding.severity === "yellow"
                                  ? "Caution"
                                  : "Info"}
                              </span>

                              {/* Category Badge */}
                              <span className="text-[11px] font-medium text-slate-300 bg-slate-800 px-2 py-0.5 rounded border border-slate-700/60">
                                {CATEGORY_LABELS[finding.category] ||
                                  finding.category}
                              </span>
                            </div>

                            {/* Clause Reference */}
                            <span
                              className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                                isSelected
                                  ? "bg-amber-500 text-zinc-950"
                                  : "bg-slate-950 text-slate-400 border border-slate-800"
                              }`}
                            >
                              Clause {finding.clause_id}
                            </span>
                          </div>

                          {/* Title & Explanation */}
                          <h3 className="text-xs font-bold text-white mb-1">
                            {finding.title}
                          </h3>
                          <p className="text-xs text-slate-300 leading-relaxed mb-3">
                            {finding.explanation}
                          </p>

                          {/* Verbatim Quoted Text Box */}
                          <div className="bg-slate-950/80 border border-slate-800/80 rounded-lg p-2.5 text-[11px] font-mono text-slate-300 leading-normal mb-2.5">
                            <span className="text-amber-400 font-bold mr-1">“</span>
                            {finding.quote}
                            <span className="text-amber-400 font-bold ml-1">”</span>
                          </div>

                          {/* Bottom Verification & Click indicator */}
                          <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[10px]">
                            <span className="flex items-center gap-1 font-medium text-emerald-400">
                              <CheckCircle2 className="w-3 h-3" />
                              {finding.verification_status === "verified"
                                ? "Exact Verified"
                                : finding.verification_status === "verified_fuzzy"
                                ? "Fuzzy Verified"
                                : "Reanchored"}{" "}
                              {finding.match_score ? `(${finding.match_score.toFixed(0)}%)` : ""}
                            </span>

                            {isSelected ? (
                              <span className="text-amber-400 font-bold flex items-center gap-1">
                                Viewing in Doc <ArrowRight className="w-3 h-3" />
                              </span>
                            ) : (
                              <span className="text-slate-500 flex items-center gap-0.5 group-hover:text-slate-300">
                                Click to highlight
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Mandatory Disclaimer Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-900/40 py-5 mt-auto">
        <div className="max-w-6xl mx-auto px-4 text-center">
          <p className="text-xs text-slate-400 font-medium">
            This tool explains documents. It is not legal advice.
          </p>
        </div>
      </footer>
    </div>
  );
}
