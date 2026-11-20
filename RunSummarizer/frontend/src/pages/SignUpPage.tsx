import React from 'react';
import { SignUp } from '@clerk/clerk-react';
import { BrandHeader } from '@/components/common/BrandHeader';

export const SignUpPage: React.FC = () => {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background text-foreground p-4">
      <BrandHeader className="mb-6" />

      <SignUp
        routing="path"
        path="/sign-up"
        signInUrl="/sign-in"
        afterSignUpUrl="/home"
      />
    </div>
  );
};

export default SignUpPage;