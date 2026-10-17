"use client";

import React, { useState, useEffect, useRef } from "react";
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
} from "lucide-react";
import {
  DocumentResponse,
  FindingModel,
  AnalysisResponse,
  SeverityLevel,
} from "@/types";

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

      // Start polling document status in the background
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

  return (
    <div className="flex flex-col min-h-screen bg-slate-950 text-slate-100">
      {/* Top Header */}
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
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
                  Phase 5
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Local-first legal Terms of Service analyzer with verified citations
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-3 text-xs">
            {backendAlive === true && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Backend Connected
              </span>
            )}
            {backendAlive === false && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
                Backend Offline (port 8000)
              </span>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8">
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
                className={`relative group border-2 border-dashed rounded-xl p-8 sm:p-12 text-center cursor-pointer transition-all ${
                  isDragOver
                    ? "border-indigo-500 bg-indigo-500/10"
                    : selectedFile
                    ? "border-emerald-500/50 bg-emerald-500/5"
                    : "border-slate-700/80 hover:border-slate-600 bg-slate-950/40 hover:bg-slate-950/70"
                }`}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.txt,application/pdf,text/plain"
                  onChange={handleFileChange}
                  className="hidden"
                />

                {selectedFile ? (
                  <div className="flex flex-col items-center">
                    <div className="h-14 w-14 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center mb-3">
                      <FileUp className="h-7 w-7 text-emerald-400" />
                    </div>
                    <span className="font-semibold text-white text-base">
                      {selectedFile.name}
                    </span>
                    <span className="text-xs text-slate-400 mt-1">
                      {(selectedFile.size / 1024).toFixed(1)} KB • Click or drop another file to replace
                    </span>
                  </div>
                ) : (
                  <div className="flex flex-col items-center">
                    <div className="h-14 w-14 rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center mb-3 group-hover:scale-105 transition-transform">
                      <Upload className="h-6 w-6 text-indigo-400" />
                    </div>
                    <p className="font-semibold text-white text-base">
                      Drag and drop your document here
                    </p>
                    <p className="text-xs text-slate-400 mt-1.5 max-w-sm">
                      Supports PDF (.pdf) or Plain Text (.txt) Terms of Service documents
                    </p>
                    <div className="mt-4 px-3 py-1.5 rounded-lg bg-slate-800 text-xs font-medium text-slate-300 border border-slate-700 shadow-sm">
                      Browse Files
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: PASTED TEXT */}
            {tab === "paste" && (
              <div>
                <div className="flex justify-between items-center mb-2">
                  <label className="text-xs font-medium text-slate-300">
                    Paste contract or Terms of Service text:
                  </label>
                  <button
                    type="button"
                    onClick={() => setPastedText(SAMPLE_TOS_TEXT)}
                    className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1 font-medium transition-colors"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    Load Sample Document
                  </button>
                </div>
                <textarea
                  rows={10}
                  value={pastedText}
                  onChange={(e) => setPastedText(e.target.value)}
                  placeholder="Paste clauses or full contract text here..."
                  className="w-full rounded-xl bg-slate-950 border border-slate-800 p-4 text-xs sm:text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 font-mono transition-all"
                />
                <div className="flex justify-between items-center mt-2 text-xs text-slate-500">
                  <span>{pastedText.length.toLocaleString()} characters</span>
                  {pastedText && (
                    <button
                      type="button"
                      onClick={() => setPastedText("")}
                      className="text-slate-400 hover:text-slate-200"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Controls Bar: Mode selector & Submit Button */}
            <div className="mt-8 pt-6 border-t border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              {/* Execution Engine Selector */}
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 bg-slate-950 p-1 rounded-xl border border-slate-800">
                  <button
                    type="button"
                    onClick={() => setIsDryRun(true)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      isDryRun
                        ? "bg-indigo-600 text-white shadow-sm"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Zap className="h-3.5 w-3.5" />
                    Fast Dry-Run ($0 / Offline)
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsDryRun(false)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      !isDryRun
                        ? "bg-indigo-600 text-white shadow-sm"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Cpu className="h-3.5 w-3.5" />
                    Local Ollama (7B)
                  </button>
                </div>
                <span className="text-[11px] text-slate-400 hidden md:inline">
                  {isDryRun
                    ? "Instant rule matching, ideal for rapid testing"
                    : "Runs local qwen2.5:7b-instruct via Ollama"}
                </span>
              </div>

              {/* Submit CTA */}
              <button
                type="button"
                onClick={handleAnalyze}
                disabled={tab === "upload" ? !selectedFile : !pastedText.trim()}
                className="w-full sm:w-auto px-6 py-3 rounded-xl bg-gradient-to-r from-indigo-500 via-indigo-600 to-violet-600 hover:from-indigo-400 hover:to-violet-500 text-white font-medium text-sm shadow-lg shadow-indigo-500/25 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 cursor-pointer"
              >
                <span>Analyze Terms of Service</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ANALYZING STATE (with Live Progress & Status Polling) */}
        {(status === "uploading" || status === "analyzing") && (
          <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-10 sm:p-14 text-center backdrop-blur-sm">
            <div className="relative inline-flex items-center justify-center mb-6">
              <div className="h-20 w-20 rounded-full border-4 border-indigo-500/20 border-t-indigo-500 animate-spin" />
              <ShieldAlert className="h-8 w-8 text-indigo-400 absolute" />
            </div>

            <h2 className="text-2xl font-bold text-white mb-2">
              Analyzing Legal Document…
            </h2>
            <p className="text-sm text-slate-400 max-w-md mx-auto mb-6">
              {progressMsg}
            </p>

            {/* Live Progress Metrics */}
            <div className="inline-flex items-center gap-4 bg-slate-950/70 border border-slate-800 px-4 py-2 rounded-xl text-xs text-slate-400">
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-indigo-400" />
                Elapsed: <strong className="text-white font-mono">{elapsedSeconds}s</strong>
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

        {/* COMPLETED STATE: Findings List */}
        {status === "done" && analysisResult && document && (
          <div className="space-y-6">
            {/* Top Document & Telemetry Header */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 backdrop-blur-sm shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 border-b border-slate-800">
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

              {/* Metrics Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
                <div className="bg-slate-950/70 p-3.5 rounded-xl border border-slate-800/80">
                  <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
                    Grounding Rate
                  </span>
                  <div className="flex items-baseline gap-1.5 mt-1">
                    <span className="text-2xl font-extrabold text-emerald-400">
                      {(analysisResult.run.grounding_rate * 100).toFixed(0)}%
                    </span>
                    <span className="text-[11px] text-slate-400">verified</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3.5 rounded-xl border border-slate-800/80">
                  <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
                    Total Findings
                  </span>
                  <div className="flex items-baseline gap-1.5 mt-1">
                    <span className="text-2xl font-extrabold text-white">
                      {findings.length}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      proposed: {analysisResult.run.proposed_count}
                    </span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3.5 rounded-xl border border-slate-800/80">
                  <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
                    Model
                  </span>
                  <div className="mt-1">
                    <span className="text-sm font-semibold text-indigo-300 truncate block">
                      {analysisResult.run.model?.replace("ollama/", "") || "stub"}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      cost: ${analysisResult.run.cost_usd.toFixed(4)}
                    </span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3.5 rounded-xl border border-slate-800/80">
                  <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
                    Latency
                  </span>
                  <div className="flex items-baseline gap-1.5 mt-1">
                    <span className="text-2xl font-extrabold text-white">
                      {analysisResult.run.latency_ms > 1000
                        ? `${(analysisResult.run.latency_ms / 1000).toFixed(1)}s`
                        : `${analysisResult.run.latency_ms.toFixed(0)}ms`}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      in: {analysisResult.run.tokens_in}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Filter Bar */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-1.5 bg-slate-900 border border-slate-800 p-1 rounded-xl text-xs">
                <button
                  type="button"
                  onClick={() => setFilterSeverity("all")}
                  className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
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
                  className={`px-3 py-1.5 rounded-lg font-medium transition-all flex items-center gap-1 ${
                    filterSeverity === "red"
                      ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                      : "text-slate-400 hover:text-rose-300"
                  }`}
                >
                  <span className="h-2 w-2 rounded-full bg-rose-400" />
                  Red Critical ({redCount})
                </button>
                <button
                  type="button"
                  onClick={() => setFilterSeverity("yellow")}
                  className={`px-3 py-1.5 rounded-lg font-medium transition-all flex items-center gap-1 ${
                    filterSeverity === "yellow"
                      ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                      : "text-slate-400 hover:text-amber-300"
                  }`}
                >
                  <span className="h-2 w-2 rounded-full bg-amber-400" />
                  Yellow Caution ({yellowCount})
                </button>
                {infoCount > 0 && (
                  <button
                    type="button"
                    onClick={() => setFilterSeverity("info")}
                    className={`px-3 py-1.5 rounded-lg font-medium transition-all flex items-center gap-1 ${
                      filterSeverity === "info"
                        ? "bg-sky-500/20 text-sky-300 border border-sky-500/30"
                        : "text-slate-400 hover:text-sky-300"
                    }`}
                  >
                    <span className="h-2 w-2 rounded-full bg-sky-400" />
                    Info ({infoCount})
                  </button>
                )}
              </div>

              <div className="text-xs text-slate-400">
                Showing {filteredFindings.length} of {findings.length} findings
              </div>
            </div>

            {/* Findings List */}
            {filteredFindings.length === 0 ? (
              <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-12 text-center">
                <CheckCircle2 className="h-10 w-10 text-emerald-400 mx-auto mb-3" />
                <h3 className="text-base font-semibold text-white">
                  No Unfair Clauses In This Category
                </h3>
                <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
                  No clauses in the document matched this severity level.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {filteredFindings.map((finding: FindingModel, idx: number) => {
                  const isRed = finding.severity === "red";
                  const isYellow = finding.severity === "yellow";

                  return (
                    <article
                      key={finding.id || idx}
                      className={`border rounded-2xl p-5 sm:p-6 transition-all shadow-md bg-slate-900/60 ${
                        isRed
                          ? "border-rose-500/20 hover:border-rose-500/40 hover:bg-slate-900/80"
                          : isYellow
                          ? "border-amber-500/20 hover:border-amber-500/40 hover:bg-slate-900/80"
                          : "border-sky-500/20 hover:border-sky-500/40 hover:bg-slate-900/80"
                      }`}
                    >
                      {/* Top Badges */}
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                        <div className="flex items-center gap-2">
                          {/* Severity Badge */}
                          <span
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider ${
                              isRed
                                ? "bg-rose-500/15 text-rose-300 border border-rose-500/30"
                                : isYellow
                                ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                                : "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                            }`}
                          >
                            {isRed && <AlertTriangle className="h-3.5 w-3.5" />}
                            {isYellow && <AlertCircle className="h-3.5 w-3.5" />}
                            {!isRed && !isYellow && <Info className="h-3.5 w-3.5" />}
                            {finding.severity}
                          </span>

                          {/* Category Tag */}
                          <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-slate-800 text-slate-300 border border-slate-700/80">
                            {CATEGORY_LABELS[finding.category] || finding.category}
                          </span>
                        </div>

                        {/* Clause & Match verification */}
                        <div className="flex items-center gap-2 text-xs">
                          <span className="font-mono text-indigo-300 bg-indigo-950/60 border border-indigo-800/60 px-2 py-0.5 rounded-md font-semibold">
                            {finding.clause_id}
                          </span>
                          <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400 bg-emerald-950/40 border border-emerald-800/40 px-2 py-0.5 rounded-md">
                            <CheckCircle2 className="h-3 w-3" />
                            {finding.verification_status} ({finding.match_score?.toFixed(0) ?? 100}%)
                          </span>
                        </div>
                      </div>

                      {/* Title & Explanation */}
                      <h3 className="text-base sm:text-lg font-bold text-white mb-2 leading-snug">
                        {finding.title}
                      </h3>
                      <p className="text-xs sm:text-sm text-slate-300 leading-relaxed mb-4">
                        {finding.explanation}
                      </p>

                      {/* Verbatim Quote Box */}
                      <div className="rounded-xl bg-slate-950/80 border border-slate-800/90 p-3.5 sm:p-4 text-xs font-mono text-slate-200">
                        <div className="flex items-center gap-1.5 text-slate-400 text-[11px] font-sans font-medium mb-1.5">
                          <span>Verified Quote from Document:</span>
                        </div>
                        <blockquote className="italic text-slate-300 border-l-2 border-indigo-500/60 pl-3 py-0.5 whitespace-pre-wrap leading-relaxed">
                          "{finding.quote}"
                        </blockquote>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </main>

      {/* Mandatory Disclaimer Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950/90 py-8 px-4 sm:px-6 mt-12 text-center text-xs">
        <div className="max-w-4xl mx-auto space-y-2">
          <p className="font-medium text-slate-300">
            This tool explains documents. It is not legal advice.
          </p>
          <p className="text-slate-400 max-w-xl mx-auto text-[11px] leading-relaxed">
            All analysis and deterministic quote verifications run on your own machine.
            Never rely solely on automated review for critical legal agreements.
          </p>
        </div>
      </footer>
    </div>
  );
}
