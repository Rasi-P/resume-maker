import axios from 'axios';

type StatusMessages = Partial<Record<number, string>>;

interface ExtractApiErrorOptions {
  statusMessages?: StatusMessages;
  unauthorizedMessage?: string;
  unauthorizedMatchers?: string[];
}

const getFirstString = (value: unknown): string | null => {
  if (typeof value === 'string' && value.trim()) {
    return value;
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = getFirstString(item);
      if (nested) {
        return nested;
      }
    }
  }

  if (typeof value === 'object' && value !== null) {
    for (const item of Object.values(value as Record<string, unknown>)) {
      const nested = getFirstString(item);
      if (nested) {
        return nested;
      }
    }
  }

  return null;
};

export const extractApiErrorMessage = (
  error: unknown,
  options: ExtractApiErrorOptions = {},
): string => {
  const {
    statusMessages = {},
    unauthorizedMessage,
    unauthorizedMatchers = [],
  } = options;

  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const apiMessage = getFirstString(error.response?.data);

    if (apiMessage) {
      const normalized = apiMessage.toLowerCase();
      if (
        unauthorizedMessage &&
        (status === 401 || unauthorizedMatchers.some((matcher) => normalized.includes(matcher)))
      ) {
        return unauthorizedMessage;
      }

      return apiMessage;
    }

    if (status && unauthorizedMessage && status === 401) {
      return unauthorizedMessage;
    }

    if (status && statusMessages[status]) {
      return statusMessages[status]!;
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return 'Request failed. Please try again.';
};