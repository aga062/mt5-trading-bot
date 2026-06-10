"use client";
import React, { useState } from "react";
import { useAuth } from "@/lib/AuthContext";
import { Lock, User, TrendingUp } from "lucide-react";

export default function AuthPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left panel */}
      <div className="hidden lg:flex lg:w-1/2 bg-gradient-to-br from-brand-950 via-surface to-surface-card items-center justify-center p-12">
        <div className="max-w-md">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-12 h-12 bg-brand-600 rounded-xl flex items-center justify-center">
              <TrendingUp className="w-7 h-7 text-white" />
            </div>
            <h1 className="text-3xl font-bold text-white">Algo Trade AI</h1>
          </div>
          <h2 className="text-4xl font-bold text-white mb-4">
            Autonomous Trading Platform
          </h2>
          <p className="text-gray-400 text-lg leading-relaxed">
            AI-powered multi-timeframe analysis with Order Block & Fair Value Gap detection.
            Connect your MT5 account and let the AI trade for you.
          </p>
          <div className="mt-10 grid grid-cols-2 gap-4">
            {[
              "H1 Trend Analysis",
              "AI Decision Engine",
              "M5 OB/FVG Zones",
              "Auto Execution",
              "Risk Management",
              "Live Streaming",
            ].map((f) => (
              <div key={f} className="flex items-center gap-2 text-gray-300">
                <div className="w-1.5 h-1.5 rounded-full bg-brand-500" />
                <span className="text-sm">{f}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          <div className="lg:hidden flex items-center gap-3 mb-8 justify-center">
            <div className="w-10 h-10 bg-brand-600 rounded-xl flex items-center justify-center">
              <TrendingUp className="w-6 h-6 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-white">Algo Trade AI</h1>
          </div>

          <h2 className="text-2xl font-bold text-white mb-1">Welcome back</h2>
          <p className="text-gray-500 mb-8">Sign in to your trading dashboard</p>

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">Username</label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  type="text"
                  className="input pl-10"
                  placeholder="Enter username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </div>
            </div>

            <div>
              <label className="label">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  type="password"
                  className="input pl-10"
                  placeholder="Enter password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
            </div>

            <button type="submit" className="btn-primary w-full" disabled={loading}>
              {loading ? "Please wait..." : "Sign In"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
