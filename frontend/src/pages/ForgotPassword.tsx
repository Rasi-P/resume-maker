import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authService } from '../services/api';
import { extractApiErrorMessage } from '../utils/apiError';

export const ForgotPassword: React.FC = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setErrorMessage('');
    setSuccessMessage('');

    try {
      const response = await authService.requestPasswordReset(email.trim());
      const uid = response?.uid;
      const token = response?.token;

      if (!uid || !token) {
        throw new Error('Unable to continue password reset. Please try again.');
      }

      setSuccessMessage(response?.message || 'Email verified. Redirecting to password reset...');
      setEmail('');
      setTimeout(() => {
        const nextUrl = `/reset-password?uid=${encodeURIComponent(uid)}&token=${encodeURIComponent(token)}`;
        navigate(nextUrl);
      }, 350);
    } catch (error) {
      setErrorMessage(
        extractApiErrorMessage(error, {
          statusMessages: {
            400: 'Please provide a valid email address.',
            500: 'Server error. Please try again later.',
          },
        })
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 to-blue-100 flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-white shadow-lg rounded-xl p-8">
        <h1 className="text-2xl font-bold text-gray-800 mb-2 text-center">Forgot Password</h1>
        <p className="text-sm text-gray-500 mb-6 text-center">
          Enter your email to verify your account and continue.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4" autoComplete="on">
          <div>
            <label
              htmlFor="forgot-password-email"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Email
            </label>
            <input
              id="forgot-password-email"
              name="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

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
            {loading ? 'Please wait...' : 'Verify Email'}
          </button>
        </form>

        <p className="text-sm text-center text-gray-600 mt-5">
          <Link to="/login" className="text-blue-600 hover:text-blue-700 hover:underline">
            Back to login
          </Link>
        </p>
      </div>
    </div>
  );
};