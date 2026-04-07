import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { staffLogin, adminLogin, authMe } from '../api/client';

type Role = 'staff' | 'admin' | null;

interface AuthState {
    authenticated: boolean;
    role: Role;
    loading: boolean;
    justLoggedOut: boolean;
    staffLoginAction: (pin: string) => Promise<boolean>;
    adminLoginAction: (username: string, password: string) => Promise<boolean>;
    adminLogout: () => void;
    logout: () => void;
    clearLoggedOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const STAFF_TOKEN_KEY = 'staff_token';
const ADMIN_TOKEN_KEY = 'admin_token';
const AUTH_TOKEN_KEY = 'auth_token'; // used by the axios interceptor

export function AuthProvider({ children }: { children: ReactNode }) {
    const [role, setRole] = useState<Role>(null);
    const [authenticated, setAuthenticated] = useState(false);
    const [loading, setLoading] = useState(true);
    const [justLoggedOut, setJustLoggedOut] = useState(false);
    const adminTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const applyToken = useCallback((token: string) => {
        localStorage.setItem(AUTH_TOKEN_KEY, token);
    }, []);

    // Check existing tokens on mount
    useEffect(() => {
        const checkAuth = async () => {
            // Try admin token first
            const adminToken = localStorage.getItem(ADMIN_TOKEN_KEY);
            if (adminToken) {
                localStorage.setItem(AUTH_TOKEN_KEY, adminToken);
                try {
                    const res = await authMe();
                    if (res.data.authenticated && res.data.role === 'admin') {
                        setRole('admin');
                        setAuthenticated(true);
                        setLoading(false);
                        return;
                    }
                } catch { /* token expired */ }
                localStorage.removeItem(ADMIN_TOKEN_KEY);
            }

            // Try staff token
            const staffToken = localStorage.getItem(STAFF_TOKEN_KEY);
            if (staffToken) {
                localStorage.setItem(AUTH_TOKEN_KEY, staffToken);
                try {
                    const res = await authMe();
                    if (res.data.authenticated) {
                        setRole('staff');
                        setAuthenticated(true);
                        setLoading(false);
                        return;
                    }
                } catch { /* token expired */ }
                localStorage.removeItem(STAFF_TOKEN_KEY);
            }

            localStorage.removeItem(AUTH_TOKEN_KEY);
            setAuthenticated(false);
            setRole(null);
            setLoading(false);
        };
        checkAuth();
    }, []);

    // Auto-expire admin mode after 30min client-side
    useEffect(() => {
        if (role === 'admin') {
            adminTimerRef.current = setTimeout(() => {
                // Revert to staff mode
                const staffToken = localStorage.getItem(STAFF_TOKEN_KEY);
                if (staffToken) {
                    localStorage.removeItem(ADMIN_TOKEN_KEY);
                    applyToken(staffToken);
                    setRole('staff');
                } else {
                    // no staff token - full logout
                    localStorage.removeItem(ADMIN_TOKEN_KEY);
                    localStorage.removeItem(AUTH_TOKEN_KEY);
                    setAuthenticated(false);
                    setRole(null);
                }
            }, 30 * 60 * 1000);
        }
        return () => {
            if (adminTimerRef.current) clearTimeout(adminTimerRef.current);
        };
    }, [role, applyToken]);

    const staffLoginAction = useCallback(async (pin: string): Promise<boolean> => {
        try {
            const res = await staffLogin(pin);
            const token = res.data.token;
            localStorage.setItem(STAFF_TOKEN_KEY, token);
            applyToken(token);
            setRole('staff');
            setAuthenticated(true);
            return true;
        } catch {
            return false;
        }
    }, [applyToken]);

    const adminLoginAction = useCallback(async (username: string, password: string): Promise<boolean> => {
        try {
            const res = await adminLogin(username, password);
            const token = res.data.token;
            localStorage.setItem(ADMIN_TOKEN_KEY, token);
            applyToken(token);
            setRole('admin');
            return true;
        } catch {
            return false;
        }
    }, [applyToken]);

    const adminLogout = useCallback(() => {
        localStorage.removeItem(ADMIN_TOKEN_KEY);
        const staffToken = localStorage.getItem(STAFF_TOKEN_KEY);
        if (staffToken) {
            applyToken(staffToken);
            setRole('staff');
        }
    }, [applyToken]);

    const logout = useCallback(() => {
        localStorage.removeItem(STAFF_TOKEN_KEY);
        localStorage.removeItem(ADMIN_TOKEN_KEY);
        localStorage.removeItem(AUTH_TOKEN_KEY);
        setAuthenticated(false);
        setRole(null);
        setJustLoggedOut(true);
    }, []);

    const clearLoggedOut = useCallback(() => {
        setJustLoggedOut(false);
    }, []);

    return (
        <AuthContext.Provider value={{ authenticated, role, loading, justLoggedOut, staffLoginAction, adminLoginAction, adminLogout, logout, clearLoggedOut }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error('useAuth must be used within AuthProvider');
    return ctx;
}
