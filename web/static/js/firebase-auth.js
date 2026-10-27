/**
 * UniClip — Firebase Authentication Client
 * Handles Google Sign-In via Firebase Web SDK (supporting both redirect and popup)
 * and exchanges the verified ID token with Flask backend session endpoint.
 */

window.initFirebaseAuth = function (firebaseConfig, csrfToken) {
  const googleBtn = document.getElementById("google-signin-btn");
  const authStatus = document.getElementById("auth-status-message");

  // Status message rendering helper
  function showStatus(message, isError = true) {
    if (!authStatus) return;
    authStatus.style.display = "block";
    if (isError) {
      authStatus.style.background = "var(--color-danger-bg, rgba(239, 68, 68, 0.15))";
      authStatus.style.color = "#f87171";
      authStatus.style.borderColor = "rgba(239, 68, 68, 0.3)";
    } else {
      authStatus.style.background = "rgba(99, 102, 241, 0.15)";
      authStatus.style.color = "#a5b4fc";
      authStatus.style.borderColor = "rgba(99, 102, 241, 0.3)";
    }
    authStatus.textContent = message;
  }

  function clearStatus() {
    if (authStatus) {
      authStatus.style.display = "none";
      authStatus.textContent = "";
    }
  }

  function setButtonLoading(loading, message = "Signing in...") {
    if (!googleBtn) return;
    googleBtn.disabled = loading;
    if (loading) {
      googleBtn.innerHTML = `
        <svg class="spinner" viewBox="0 0 50 50" style="width:18px;height:18px;animation:spin 1s linear infinite;margin-right:8px;">
          <circle cx="25" cy="25" r="20" fill="none" stroke="currentColor" stroke-width="5" stroke-dasharray="31.4 31.4"></circle>
        </svg>
        ${message}
      `;
    } else {
      googleBtn.innerHTML = `
        <svg viewBox="0 0 24 24" width="18" height="18" style="margin-right:8px;">
          <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
          <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
          <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
          <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
        </svg>
        Sign in with Google
      `;
    }
  }

  function handleAuthError(err) {
    const code = (err && err.code) || "";
    const msg = (err && err.message) || "";

    if (code === "auth/popup-blocked") {
      showStatus("Sign-in popup was blocked by your browser. Retrying with redirect...", true);
    } else if (code === "auth/popup-closed-by-user") {
      showStatus("Sign-in window was closed before completion.", true);
    } else if (code === "auth/network-request-failed" || msg.toLowerCase().includes("failed to fetch")) {
      showStatus("Network connection failed. Please check your internet connection or USB port forwarding.", true);
    } else if (code === "auth/unauthorized-domain") {
      showStatus("This domain is not authorized in Firebase Authentication Console.", true);
    } else if (code === "auth/account-exists-with-different-credential") {
      showStatus("An account already exists with the same email using a different provider.", true);
    } else if (msg) {
      showStatus(msg, true);
    } else {
      showStatus("Sign-in failed. Please try again.", true);
    }
  }

  // Token exchange helper
  async function exchangeSessionToken(user) {
    if (!user) return;
    setButtonLoading(true, "Completing sign-in...");
    showStatus("Establishing secure session...", false);

    try {
      const idToken = await user.getIdToken();
      const resp = await fetch("/api/auth/session", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ id_token: idToken }),
      });

      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data.success) {
        window.location.href = "/dashboard";
      } else {
        throw new Error(data.error || "Server rejected session creation.");
      }
    } catch (err) {
      console.error("Session exchange error:", err.name || "network_error");
      handleAuthError(err);
      setButtonLoading(false);
    }
  }

  // Ensure Firebase is initialized on page load
  let authInitialized = false;
  try {
    if (typeof firebase !== "undefined" && firebase.auth) {
      if (!firebase.apps.length && firebaseConfig && firebaseConfig.apiKey) {
        firebase.initializeApp(firebaseConfig);
      }
      authInitialized = true;
    }
  } catch (err) {
    console.error("Firebase init error:", err.code || err.name);
  }

  // Handle redirect result immediately upon page load
  if (authInitialized) {
    firebase.auth().getRedirectResult()
      .then(async (result) => {
        if (result && result.user) {
          await exchangeSessionToken(result.user);
        }
      })
      .catch((err) => {
        console.error("Redirect sign-in error code:", err.code || "unknown");
        handleAuthError(err);
        setButtonLoading(false);
      });
  }

  // Google Sign-In Button Click Handler
  if (googleBtn) {
    googleBtn.addEventListener("click", async () => {
      clearStatus();
      setButtonLoading(true, "Connecting to Google...");

      try {
        if (typeof firebase === "undefined" || !firebase.auth) {
          throw new Error("Firebase SDK not loaded or network unavailable.");
        }

        if (!firebase.apps.length && firebaseConfig) {
          firebase.initializeApp(firebaseConfig);
        }

        const provider = new firebase.auth.GoogleAuthProvider();
        provider.addScope("email");
        provider.addScope("profile");

        // Mobile detection: Android / iOS / small touch screen devices
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth <= 768;

        if (isMobile) {
          // Mobile browsers reliably handle redirect sign-in without popup blocker conflicts
          await firebase.auth().signInWithRedirect(provider);
          return;
        }

        // Desktop: Try popup first, fall back smoothly to redirect if popup is blocked
        try {
          const result = await firebase.auth().signInWithPopup(provider);
          if (result && result.user) {
            await exchangeSessionToken(result.user);
          }
        } catch (popupErr) {
          if (popupErr.code === "auth/popup-blocked" || popupErr.code === "auth/popup-closed-by-user") {
            console.warn("Popup blocked or closed, falling back to redirect flow.");
            await firebase.auth().signInWithRedirect(provider);
            return;
          }
          throw popupErr;
        }
      } catch (err) {
        console.error("Sign-in error:", err.code || err.name);
        handleAuthError(err);
        setButtonLoading(false);
      }
    });
  }

  // Dev Mock Sign-In handler (only active when dev_mock_auth is true)
  const devMockBtn = document.getElementById("dev-mock-signin-btn");
  if (devMockBtn) {
    devMockBtn.addEventListener("click", async () => {
      devMockBtn.disabled = true;
      devMockBtn.textContent = "Authenticating dev session...";
      clearStatus();
      try {
        const resp = await fetch("/api/auth/session", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
          body: JSON.stringify({ id_token: "mock-valid-token-devuser" }),
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok && data.success) {
          window.location.href = "/dashboard";
        } else {
          showStatus("Dev mock login failed: " + (data.error || "Unknown error"), true);
        }
      } catch (e) {
        showStatus("Dev mock login network error: " + (e.message || "Failed to fetch"), true);
      } finally {
        devMockBtn.disabled = false;
        devMockBtn.textContent = "⚡ Fast Dev Sign-In (Local Test)";
      }
    });
  }

  // Guest Mode Sign-In Handler
  const guestBtn = document.getElementById("guest-signin-btn");
  if (guestBtn) {
    guestBtn.addEventListener("click", async () => {
      guestBtn.disabled = true;
      const originalText = guestBtn.innerHTML;
      guestBtn.innerHTML = `
        <svg class="spinner" viewBox="0 0 50 50" style="width:16px;height:16px;animation:spin 1s linear infinite;margin-right:8px;">
          <circle cx="25" cy="25" r="20" fill="none" stroke="currentColor" stroke-width="5" stroke-dasharray="31.4 31.4"></circle>
        </svg>
        Starting Guest Session...
      `;
      clearStatus();

      try {
        const resp = await fetch("/api/auth/guest-session", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok && data.success) {
          window.location.href = "/dashboard";
        } else {
          showStatus("Unable to start guest mode: " + (data.error || "Unknown server response"), true);
          guestBtn.disabled = false;
          guestBtn.innerHTML = originalText;
        }
      } catch (err) {
        showStatus("Network connection failed starting guest session.", true);
        guestBtn.disabled = false;
        guestBtn.innerHTML = originalText;
      }
    });
  }
};

