import React from "react";
import { createRoot } from "react-dom/client";
import { AuthProvider, useAuth } from "../../lib/firebase/auth-context";

function ProfileSignOut() {
  const { user, loading, signOut } = useAuth();
  return <main>
    <h1>Profile</h1>
    <p>{loading ? "Signing out" : user ? "Connected" : "Signed out"}</p>
    <button disabled={loading || !user} onClick={() => void signOut()}>Sign out</button>
  </main>;
}

createRoot(document.getElementById("root")!).render(<AuthProvider><ProfileSignOut /></AuthProvider>);
