import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../services/api';

type AuthMode = 'login' | 'register';

const defaultFormState = {
  username: '',
  email: '',
  password: '',
  passwordConfirm: '',
};

const extractErrorMessage = (error: unknown): string => {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  if (typeof error !== 'object' || error === null) {
    return 'Request failed. Please try again.';
  }

  const maybeResponse = error as {
    response?: {
      data?: unknown;
    };
  };

  const data = maybeResponse.response?.data;
  if (typeof data === 'string') {
    return data;
  }

  if (typeof data === 'object' && data !== null) {
    const entries = Object.values(data as Record<string, unknown>);
    const first = entries[0];

    if (Array.isArray(first) && first.length > 0) {
      return String(first[0]);
    }

    if (typeof first === 'string') {
      return first;
    }
  }

  return 'Request failed. Please try again.';
};

export const Auth: React.FC = () => {
  const navigate = useNavigate();
  const [mode, setMode] = useState<AuthMode>('login');
  const [formState, setFormState] = useState(defaultFormState);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const handleModeChange = (nextMode: AuthMode) => {
    setMode(nextMode);
    setErrorMessage('');
    setSuccessMessage('');
  };

  const updateField =
    (field: keyof typeof defaultFormState) =>
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setFormState((prev) => ({ ...prev, [field]: event.target.value }));
    };

  const handleLogin = async () => {
    const username = formState.username.trim();
    const password = formState.password;

    if (!username || !password) {
      throw new Error('Username and password are required.');
    }

    await authService.login(username, password);
    navigate('/resume-optimizer', { replace: true });
  };

  const handleRegister = async () => {
    await authService.register(
      formState.username.trim(),
      formState.email.trim(),
      formState.password,
      formState.passwordConfirm
    );

    setSuccessMessage('Registration successful. Please login.');
    setMode('login');
    setFormState((prev) => ({
      ...prev,
      password: '',
      passwordConfirm: '',
    }));
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setErrorMessage('');
    setSuccessMessage('');

    try {
      if (mode === 'login') {
        await handleLogin();
      } else {
        await handleRegister();
      }
    } catch (error) {
      setErrorMessage(extractErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 to-blue-100 flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-white shadow-lg rounded-xl p-8">
        <h1 className="text-3xl font-bold text-gray-800 mb-2 text-center">Resume Maker</h1>
        <p className="text-sm text-gray-500 mb-6 text-center">
          Login to access resume optimization tools
        </p>

        <div className="grid grid-cols-2 gap-2 mb-6">
          <button
            type="button"
            onClick={() => handleModeChange('login')}
            className={`py-2 rounded-md text-sm font-medium ${
              mode === 'login'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            Login
          </button>
          <button
            type="button"
            onClick={() => handleModeChange('register')}
            className={`py-2 rounded-md text-sm font-medium ${
              mode === 'register'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            Register
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input
              type="text"
              value={formState.username}
              onChange={updateField('username')}
              required
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {mode === 'register' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input
                type="email"
                value={formState.email}
                onChange={updateField('email')}
                required
                className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={formState.password}
              onChange={updateField('password')}
              required
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {mode === 'register' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Confirm Password
              </label>
              <input
                type="password"
                value={formState.passwordConfirm}
                onChange={updateField('passwordConfirm')}
                required
                className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          )}

          {errorMessage && (
            <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-3">
              {errorMessage}
            </div>
          )}

          {successMessage && (
            <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-md p-3">
              {successMessage}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 disabled:bg-gray-400"
          >
            {loading ? 'Please wait...' : mode === 'login' ? 'Login' : 'Create Account'}
          </button>
        </form>
      </div>
    </div>
  );
};
