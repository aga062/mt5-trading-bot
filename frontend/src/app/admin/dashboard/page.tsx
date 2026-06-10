"use client";
import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { adminApi, User } from "@/lib/api";
import {
  Shield, Users, Plus, Trash2, Edit2, X, Save, LogOut,
  User as UserIcon, Mail, Lock
} from "lucide-react";

export default function AdminDashboard() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  const [form, setForm] = useState({
    username: "",
    email: "",
    password: "",
    role: "user",
  });

  const [editForm, setEditForm] = useState({
    username: "",
    email: "",
    password: "",
    role: "user",
  });

  // Protect route
  useEffect(() => {
    if (!user) return;
    if (user.role !== "admin") {
      router.push("/");
    }
  }, [user, router]);

  const loadUsers = async () => {
    try {
      setLoading(true);
      const data = await adminApi.listUsers();
      setUsers(data);
    } catch (err: any) {
      setError(err.message || "Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.role === "admin") {
      loadUsers();
    }
  }, [user]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await adminApi.createUser(form);
      setForm({ username: "", email: "", password: "", role: "user" });
      setShowCreate(false);
      await loadUsers();
    } catch (err: any) {
      setError(err.message || "Failed to create user");
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingId) return;
    try {
      const payload: any = {};
      if (editForm.username) payload.username = editForm.username;
      if (editForm.email) payload.email = editForm.email;
      if (editForm.password) payload.password = editForm.password;
      if (editForm.role) payload.role = editForm.role;
      await adminApi.updateUser(editingId, payload);
      setEditingId(null);
      await loadUsers();
    } catch (err: any) {
      setError(err.message || "Failed to update user");
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this user? This cannot be undone.")) return;
    try {
      await adminApi.deleteUser(id);
      await loadUsers();
    } catch (err: any) {
      setError(err.message || "Failed to delete user");
    }
  };

  const startEdit = (u: User) => {
    setEditingId(u.id);
    setEditForm({
      username: u.username,
      email: u.email,
      password: "",
      role: u.role,
    });
  };

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-brand-950 via-surface to-surface-card p-6">
      {/* Header */}
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-brand-600 rounded-xl flex items-center justify-center">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Admin Dashboard</h1>
              <p className="text-gray-500 text-sm">Manage users and accounts</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-gray-400 text-sm">{user.username}</span>
            <button
              onClick={() => { logout(); router.push("/admin"); }}
              className="btn-outline text-xs flex items-center gap-1.5"
            >
              <LogOut className="w-3.5 h-3.5" /> Logout
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-6">
            {error}
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <div className="card flex items-center gap-4">
            <div className="p-2.5 rounded-lg bg-surface text-brand-400">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <p className="stat-label">Total Users</p>
              <p className="stat-value text-white">{users.length}</p>
            </div>
          </div>
          <div className="card flex items-center gap-4">
            <div className="p-2.5 rounded-lg bg-surface text-profit">
              <Shield className="w-5 h-5" />
            </div>
            <div>
              <p className="stat-label">Admins</p>
              <p className="stat-value text-white">{users.filter((u) => u.role === "admin").length}</p>
            </div>
          </div>
          <div className="card flex items-center gap-4">
            <div className="p-2.5 rounded-lg bg-surface text-brand-400">
              <UserIcon className="w-5 h-5" />
            </div>
            <div>
              <p className="stat-label">Regular Users</p>
              <p className="stat-value text-white">{users.filter((u) => u.role === "user").length}</p>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex justify-end mb-4">
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="btn-primary text-sm flex items-center gap-1.5"
          >
            {showCreate ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
            {showCreate ? "Cancel" : "Create User"}
          </button>
        </div>

        {/* Create User Form */}
        {showCreate && (
          <div className="card mb-6">
            <h3 className="font-semibold text-white mb-4">Create New User</h3>
            <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <label className="label">Username</label>
                <input
                  type="text"
                  className="input"
                  placeholder="Username"
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  required
                />
              </div>
              <div>
                <label className="label">Email</label>
                <input
                  type="email"
                  className="input"
                  placeholder="Email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  required
                />
              </div>
              <div>
                <label className="label">Password</label>
                <input
                  type="password"
                  className="input"
                  placeholder="Password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  required
                />
              </div>
              <div>
                <label className="label">Role</label>
                <select
                  className="input"
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                >
                  <option value="user">User</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div className="sm:col-span-2 lg:col-span-4 flex justify-end">
                <button type="submit" className="btn-primary text-sm flex items-center gap-1.5">
                  <Save className="w-4 h-4" /> Create User
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Users Table */}
        <div className="card overflow-x-auto">
          <h3 className="font-semibold text-white mb-4">All Users</h3>
          {loading ? (
            <p className="text-gray-500 text-center py-8">Loading users...</p>
          ) : users.length === 0 ? (
            <p className="text-gray-500 text-center py-8">No users found</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border text-gray-400 text-left">
                  <th className="pb-2 pr-4 font-medium">ID</th>
                  <th className="pb-2 pr-4 font-medium">Username</th>
                  <th className="pb-2 pr-4 font-medium">Email</th>
                  <th className="pb-2 pr-4 font-medium">Role</th>
                  <th className="pb-2 pr-4 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="text-gray-200">
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-surface-border/50">
                    {editingId === u.id ? (
                      <>
                        <td className="py-2 pr-4 text-gray-500">{u.id}</td>
                        <td className="py-2 pr-4">
                          <input
                            type="text"
                            className="input py-1 px-2 text-sm"
                            value={editForm.username}
                            onChange={(e) => setEditForm({ ...editForm, username: e.target.value })}
                          />
                        </td>
                        <td className="py-2 pr-4">
                          <input
                            type="email"
                            className="input py-1 px-2 text-sm"
                            value={editForm.email}
                            onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                          />
                        </td>
                        <td className="py-2 pr-4">
                          <select
                            className="input py-1 px-2 text-sm"
                            value={editForm.role}
                            onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                          >
                            <option value="user">User</option>
                            <option value="admin">Admin</option>
                          </select>
                        </td>
                        <td className="py-2 pr-4 text-right">
                          <form onSubmit={handleUpdate} className="inline">
                            <button type="submit" className="text-profit hover:text-emerald-400 mr-3">
                              <Save className="w-4 h-4 inline" />
                            </button>
                          </form>
                          <button
                            onClick={() => setEditingId(null)}
                            className="text-gray-500 hover:text-gray-300"
                          >
                            <X className="w-4 h-4 inline" />
                          </button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="py-2 pr-4 text-gray-500">{u.id}</td>
                        <td className="py-2 pr-4 font-medium">{u.username}</td>
                        <td className="py-2 pr-4">{u.email}</td>
                        <td className="py-2 pr-4">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                              u.role === "admin"
                                ? "bg-brand-500/20 text-brand-400"
                                : "bg-gray-700/50 text-gray-400"
                            }`}
                          >
                            {u.role}
                          </span>
                        </td>
                        <td className="py-2 pr-4 text-right">
                          <button
                            onClick={() => startEdit(u)}
                            className="text-brand-400 hover:text-brand-300 mr-3"
                          >
                            <Edit2 className="w-4 h-4 inline" />
                          </button>
                          <button
                            onClick={() => handleDelete(u.id)}
                            className="text-red-400 hover:text-red-300"
                          >
                            <Trash2 className="w-4 h-4 inline" />
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
