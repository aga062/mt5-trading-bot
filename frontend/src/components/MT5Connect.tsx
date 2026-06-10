"use client";
import React, { useState } from "react";
import { mt5Api, MT5Status } from "@/lib/api";
import { Server, Hash, Lock, X, Loader2 } from "lucide-react";

interface Props {
  onConnected: (status: MT5Status) => void;
  onClose: () => void;
}

export default function MT5Connect({ onConnected, onClose }: Props) {
  const [server, setServer] = useState("");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const status = await mt5Api.connect({ server, login, password });
      if (status.connected) {
        onConnected(status);
      } else {
        setError(status.error || "Connection failed");
      }
    } catch (err: any) {
      setError(err.message || "Connection failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card relative">
      <button onClick={onClose}
        className="absolute top-4 right-4 text-gray-500 hover:text-gray-300">
        <X className="w-5 h-5" />
      </button>

      <h2 className="text-xl font-bold text-white mb-1">Connect to MetaTrader 5</h2>
      <p className="text-gray-500 text-sm mb-6">Enter your MT5 account credentials</p>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
          {error}
        </div>
      )}

      <form onSubmit={handleConnect} className="space-y-4">
        <div>
          <label className="label">MT5 Server</label>
          <div className="relative">
            <Server className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input type="text" className="input pl-10" placeholder="e.g. MetaQuotes-Demo"
              value={server} onChange={(e) => setServer(e.target.value)} required />
          </div>
        </div>
        <div>
          <label className="label">MT5 Login</label>
          <div className="relative">
            <Hash className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input type="text" className="input pl-10" placeholder="Account number"
              value={login} onChange={(e) => setLogin(e.target.value)} required />
          </div>
        </div>
        <div>
          <label className="label">MT5 Password</label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input type="password" className="input pl-10" placeholder="Password"
              value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
        </div>
        <button type="submit" className="btn-primary w-full flex items-center justify-center gap-2" disabled={loading}>
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? "Connecting..." : "Connect to MT5"}
        </button>
      </form>
    </div>
  );
}
