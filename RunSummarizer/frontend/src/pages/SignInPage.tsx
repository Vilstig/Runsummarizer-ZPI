import React from 'react';
import { SignIn } from '@clerk/clerk-react';
import { BrandHeader } from '@/components/common/BrandHeader';

export const SignInPage: React.FC = () => {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background text-foreground p-4">
      <BrandHeader className="mb-6" />

      <SignIn
        routing="path"
        path="/sign-in"
        signUpUrl="/sign-up"
        afterSignInUrl="/home"
      />
    </div>
  );
};

export default SignInPage;